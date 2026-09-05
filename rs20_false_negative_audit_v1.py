# -*- coding: utf-8 -*-
import csv, gzip, getpass, time
from collections import defaultdict
from datetime import datetime
from pathlib import Path
import requests

BASE_URL='https://api.kiwoom.com'
TOKEN_URL=BASE_URL+'/oauth2/token'
CHART_URL=BASE_URL+'/api/dostk/chart'
API_ID='ka10080'
API_MIN_INTERVAL=0.35
RETRY_DELAYS=[1.5,3.0,6.0,10.0]
PREFILTER_FILE='rs20_history_daily_prefilter_v1.csv'
CORRECTED_FILE='rs20_numeric_candidates_corrected_v1.csv'
PROGRESS_FILE='rs20_false_negative_audit_stock_progress_v1.csv'
RESULT_FILE='rs20_false_negative_audit_all_dates_v1.csv'
FINAL_FILE='rs20_numeric_candidates_final_audited_v1.csv'
NEW_FILE='rs20_false_negative_new_candidates_v1.csv'
MISSING_FILE='rs20_false_negative_missing_dates_v1.csv'
SUMMARY_FILE='rs20_false_negative_audit_summary_v1.txt'
CACHE_ROOT='common_market_data/minute_1m_stock_v1'
CACHE_MANIFEST='common_market_data/minute_1m_stock_manifest_v1.csv'

PROGRESS_FIELDS=['stock_code','stock_name','market','target_dates','seen_dates','missing_dates','candidate_dates','pages','bars_unique','oldest_target','oldest_bar','newest_bar','status','error','completed_at']
RESULT_FIELDS=['stock_code','stock_name','market','trade_date','traded_value_eok','m_value_eok','m_ratio_pct','approx_minute_turnover_eok','turnover_vs_daily_pct','bar_count','numeric_pass','was_in_corrected_1144','classification']
MANIFEST_FIELDS=['stock_code','stock_name','market','oldest_bar','newest_bar','bars_unique','cache_file','saved_at']

class RateLimiter:
    def __init__(self, interval): self.interval,self.last=interval,0.0
    def wait(self):
        gap=time.monotonic()-self.last
        if gap<self.interval: time.sleep(self.interval-gap)
        self.last=time.monotonic()
RATE=RateLimiter(API_MIN_INTERVAL)

def sf(v,default=None):
    try:
        if v is None or str(v).strip()=='': return default
        return float(str(v).replace(',','').replace('+','').strip())
    except: return default

def af(v,default=None):
    x=sf(v,default); return abs(x) if x is not None else default

def norm_code(v):
    s=str(v).strip()
    if s.endswith('.0') and s[:-2].isdigit(): s=s[:-2]
    return s.zfill(6)

def read_csv(path):
    if not path.exists(): return []
    with path.open('r',encoding='utf-8-sig',newline='') as f: return list(csv.DictReader(f))

def append_row(path,fields,row):
    path.parent.mkdir(parents=True,exist_ok=True)
    exists=path.exists() and path.stat().st_size>0
    with path.open('a',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=fields,extrasaction='ignore')
        if not exists: w.writeheader()
        w.writerow(row)

def write_all(path,fields,rows):
    path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_suffix(path.suffix+'.tmp')
    with tmp.open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=fields,extrasaction='ignore'); w.writeheader(); w.writerows(rows)
    tmp.replace(path)

def get_token(app,secret):
    last=None
    for i in range(len(RETRY_DELAYS)+1):
        try:
            r=requests.post(TOKEN_URL,json={'grant_type':'client_credentials','appkey':app,'secretkey':secret},timeout=20)
            r.raise_for_status(); d=r.json(); token=d.get('token')
            if not token: raise RuntimeError('TOKEN issue: '+str(d))
            return token
        except Exception as e:
            last=e
            if i>=len(RETRY_DELAYS): break
            delay=RETRY_DELAYS[i]; print(f'[TOKEN RETRY {i+1}] {e} / {delay:.1f}s'); time.sleep(delay)
    raise last

def request_page(token,code,cont_yn=None,next_key=None):
    headers={'Content-Type':'application/json;charset=UTF-8','authorization':'Bearer '+token,'api-id':API_ID,'Connection':'close'}
    if cont_yn: headers['cont-yn']=cont_yn
    if next_key: headers['next-key']=next_key
    body={'stk_cd':code,'tic_scope':'1','upd_stkpc_tp':'0'}
    last=None
    for i in range(len(RETRY_DELAYS)+1):
        try:
            RATE.wait(); r=requests.post(CHART_URL,headers=headers,json=body,timeout=30)
            if r.status_code==429 or 500<=r.status_code<=599: raise requests.HTTPError(f'retryable HTTP {r.status_code}: {r.text[:160]}')
            r.raise_for_status(); d=r.json()
            if int(d.get('return_code',0))!=0: raise RuntimeError(str(d))
            return d.get('stk_min_pole_chart_qry') or [],str(r.headers.get('cont-yn','')).strip(),str(r.headers.get('next-key','')).strip()
        except Exception as e:
            last=e
            if i>=len(RETRY_DELAYS): break
            delay=RETRY_DELAYS[i]; print(f'[RETRY {code} {i+1}/{len(RETRY_DELAYS)}] {e} / {delay:.1f}s'); time.sleep(delay)
    raise last

def parse_bar(r):
    tm=str(r.get('cntr_tm','')).strip()
    if len(tm)!=14 or not tm.isdigit(): return None
    o,h,l,c,v=af(r.get('open_pric')),af(r.get('high_pric')),af(r.get('low_pric')),af(r.get('cur_prc')),af(r.get('trde_qty'),0.0)
    if None in (o,h,l,c): return None
    return {'cntr_tm':tm,'open_pric':o,'high_pric':h,'low_pric':l,'cur_prc':c,'trde_qty':v or 0.0}

def save_stock_cache(path,bars):
    path.parent.mkdir(parents=True,exist_ok=True); tmp=path.with_suffix(path.suffix+'.tmp')
    fields=['cntr_tm','open_pric','high_pric','low_pric','cur_prc','trde_qty']
    with gzip.open(tmp,'wt',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=fields); w.writeheader()
        for tm in sorted(bars): w.writerow(bars[tm])
    tmp.replace(path)

def calc_m(daybars):
    m=turn=0.0
    for b in daybars:
        typical=(b['high_pric']+b['open_pric']+b['low_pric']+b['cur_prc'])/4.0
        eok=typical*b['trde_qty']/100000000.0; turn+=eok
        if b['cur_prc']>b['open_pric']: m+=eok
        elif b['cur_prc']<b['open_pric']: m-=eok
    return m,turn

def main():
    base=Path(__file__).resolve().parent
    pre_path=base/PREFILTER_FILE; corr_path=base/CORRECTED_FILE
    if not pre_path.exists(): raise SystemExit('REQUIRED FILE NOT FOUND: '+PREFILTER_FILE)
    if not corr_path.exists(): raise SystemExit('REQUIRED FILE NOT FOUND: '+CORRECTED_FILE)
    pre=read_csv(pre_path); corrected=read_csv(corr_path)
    corrected_keys={(norm_code(r.get('stock_code','')),str(r.get('trade_date','')).strip()) for r in corrected}
    targets=defaultdict(dict); meta={}
    for r in pre:
        code=norm_code(r.get('stock_code','')); dt=str(r.get('trade_date','')).strip()
        if len(dt)!=8 or not dt.isdigit(): continue
        tv=sf(r.get('traded_value_eok'))
        if tv is None:
            raw=sf(r.get('trde_prica'))
            if raw is not None: tv=raw/100.0
        if tv is None or tv<200.0: continue
        targets[code][dt]={'traded_value_eok':tv,'stock_name':r.get('stock_name',''),'market':r.get('market','')}
        meta[code]={'stock_name':r.get('stock_name',''),'market':r.get('market','')}
    stocks=sorted(targets)
    progress_path=base/PROGRESS_FILE; result_path=base/RESULT_FILE
    done={norm_code(r.get('stock_code','')) for r in read_csv(progress_path) if str(r.get('status','')).strip()=='DONE'}
    print('='*78); print('RS20 False-Negative Audit v1'); print(f'PHASE A target rows : {sum(len(v) for v in targets.values()):,}'); print(f'Target stocks       : {len(stocks):,}'); print(f'Already DONE        : {len(done):,}'); print(f'Remaining stocks    : {len(stocks)-len(done):,}'); print('NO ORDER API'); print('='*78)
    if len(done)<len(stocks):
        app=getpass.getpass('Kiwoom App Key: ').strip(); secret=getpass.getpass('Kiwoom Secret Key: ').strip(); token=get_token(app,secret); print('TOKEN success')
        try:
            for si,code in enumerate(stocks,1):
                if code in done: continue
                tdict=targets[code]; dates=sorted(tdict); oldest_target=dates[0]; name=meta[code]['stock_name']; market=meta[code]['market']
                bars={}; cont=None; nkey=None; pages=0; oldest_bar=''; newest_bar=''
                try:
                    while True:
                        rows,resp_cont,resp_next=request_page(token,code,cont,nkey); pages+=1; pdates=[]
                        for raw in rows:
                            b=parse_bar(raw)
                            if not b: continue
                            tm=b['cntr_tm']; pdates.append(tm[:8])
                            if tm not in bars: bars[tm]=b
                        if pdates:
                            pmin,pmax=min(pdates),max(pdates); oldest_bar=pmin if not oldest_bar else min(oldest_bar,pmin); newest_bar=pmax if not newest_bar else max(newest_bar,pmax)
                        if oldest_bar and oldest_bar<=oldest_target: break
                        if resp_cont.upper()!='Y' or not resp_next: break
                        cont,nkey=resp_cont,resp_next
                    cp=base/CACHE_ROOT/f'{code}.csv.gz'; save_stock_cache(cp,bars)
                    bydate=defaultdict(list)
                    for tm,b in bars.items():
                        dt=tm[:8]
                        if dt in tdict: bydate[dt].append(b)
                    seen=missing=cands=0
                    for dt in dates:
                        day=sorted(bydate.get(dt,[]),key=lambda x:x['cntr_tm'])
                        if not day: missing+=1; continue
                        seen+=1; m,turn=calc_m(day); tv=tdict[dt]['traded_value_eok']; ratio=m/tv*100 if tv else None; tratio=turn/tv*100 if tv else None; passed=m>=200 and ratio is not None and ratio>=20
                        key=(code,dt); old=key in corrected_keys
                        cls='CONFIRMED_OLD' if passed and old else 'NEW_FALSE_NEGATIVE' if passed else 'REMOVED_OLD' if old else 'NON_CANDIDATE'
                        if passed: cands+=1
                        append_row(result_path,RESULT_FIELDS,{'stock_code':code,'stock_name':name,'market':market,'trade_date':dt,'traded_value_eok':tv,'m_value_eok':round(m,6),'m_ratio_pct':round(ratio,6) if ratio is not None else '','approx_minute_turnover_eok':round(turn,6),'turnover_vs_daily_pct':round(tratio,6) if tratio is not None else '','bar_count':len(day),'numeric_pass':'Y' if passed else 'N','was_in_corrected_1144':'Y' if old else 'N','classification':cls})
                    append_row(progress_path,PROGRESS_FIELDS,{'stock_code':code,'stock_name':name,'market':market,'target_dates':len(dates),'seen_dates':seen,'missing_dates':missing,'candidate_dates':cands,'pages':pages,'bars_unique':len(bars),'oldest_target':oldest_target,'oldest_bar':oldest_bar,'newest_bar':newest_bar,'status':'DONE','error':'','completed_at':datetime.now().strftime('%Y%m%d%H%M%S')})
                    append_row(base/CACHE_MANIFEST,MANIFEST_FIELDS,{'stock_code':code,'stock_name':name,'market':market,'oldest_bar':oldest_bar,'newest_bar':newest_bar,'bars_unique':len(bars),'cache_file':str(cp.relative_to(base)).replace('\\','/'),'saved_at':datetime.now().strftime('%Y%m%d%H%M%S')})
                    print(f'[{si:04d}/{len(stocks)}] {code} {name} | target {len(dates)} seen {seen} miss {missing} | cand {cands} | pages {pages} | bars {len(bars):,}')
                except Exception as e:
                    append_row(progress_path,PROGRESS_FIELDS,{'stock_code':code,'stock_name':name,'market':market,'target_dates':len(dates),'oldest_target':oldest_target,'status':'ERROR','error':repr(e),'completed_at':datetime.now().strftime('%Y%m%d%H%M%S')}); print(f'[ERROR - retry next run] {code} {name}: {e}')
        except KeyboardInterrupt:
            print('\nCtrl+C detected. Completed stocks are preserved. Run the same BAT to resume.'); return
    all_rows=read_csv(result_path); latest={}
    for r in all_rows: latest[(norm_code(r.get('stock_code','')),str(r.get('trade_date','')).strip())]=r
    audited=list(latest.values()); final=[r for r in audited if r.get('numeric_pass')=='Y']; new=[r for r in final if r.get('was_in_corrected_1144')!='Y']
    result_keys=set(latest); missing=[]
    for code,tdict in targets.items():
        for dt,md in tdict.items():
            if (code,dt) not in result_keys: missing.append({'stock_code':code,'stock_name':md.get('stock_name',''),'market':md.get('market',''),'trade_date':dt,'traded_value_eok':md.get('traded_value_eok','')})
    final.sort(key=lambda r:(r['trade_date'],r['stock_code'])); new.sort(key=lambda r:(r['trade_date'],r['stock_code'])); missing.sort(key=lambda r:(r['trade_date'],r['stock_code']))
    write_all(base/FINAL_FILE,RESULT_FIELDS,final); write_all(base/NEW_FILE,RESULT_FIELDS,new); write_all(base/MISSING_FILE,['stock_code','stock_name','market','trade_date','traded_value_eok'],missing)
    progress=read_csv(progress_path); done_stocks={norm_code(r.get('stock_code','')) for r in progress if str(r.get('status','')).strip()=='DONE'}; err_stocks={norm_code(r.get('stock_code','')) for r in progress if str(r.get('status','')).strip()=='ERROR'}-done_stocks
    confirmed=sum(1 for r in final if r.get('was_in_corrected_1144')=='Y')
    lines=['RS20 False-Negative Audit v1',f'run_at: {datetime.now().isoformat(timespec="seconds")}',f'phase_a_target_rows: {sum(len(v) for v in targets.values())}',f'target_stocks: {len(stocks)}',f'done_stocks: {len(done_stocks)}',f'unresolved_error_stocks: {len(err_stocks)}',f'audited_stock_dates_with_minute_data: {len(audited)}',f'missing_target_dates: {len(missing)}','',f'old_corrected_candidates: {len(corrected_keys)}',f'confirmed_old_candidates: {confirmed}',f'old_candidates_missing_or_removed: {len(corrected_keys)-confirmed}',f'new_false_negative_candidates: {len(new)}',f'final_audited_numeric_candidates: {len(final)}','','METHOD: corrected pagination, upd_stkpc_tp=0, exact cntr_tm dedup, stock-level gzip cache','IMPORTANT: missing dates are not treated as non-candidates. NO ORDER API.']
    (base/SUMMARY_FILE).write_text('\n'.join(lines)+'\n',encoding='utf-8')
    print('='*78); print('AUDIT COMPLETE / CURRENT STATE'); print(f'DONE STOCKS          : {len(done_stocks):,} / {len(stocks):,}'); print(f'UNRES ERROR STOCKS   : {len(err_stocks):,}'); print(f'AUDITED DATES        : {len(audited):,}'); print(f'MISSING DATES        : {len(missing):,}'); print(f'OLD CORRECTED        : {len(corrected_keys):,}'); print(f'NEW FALSE NEGATIVE   : {len(new):,}'); print(f'FINAL NUMERIC PASS   : {len(final):,}'); print(f'FINAL FILE           : {FINAL_FILE}'); print(f'NEW FILE             : {NEW_FILE}'); print(f'MISSING FILE         : {MISSING_FILE}'); print(f'SUMMARY              : {SUMMARY_FILE}'); print(f'CACHE ROOT           : {CACHE_ROOT}'); print('='*78)

if __name__=='__main__': main()
