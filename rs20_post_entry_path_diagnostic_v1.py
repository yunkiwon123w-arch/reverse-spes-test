# -*- coding: utf-8 -*-
import csv, gzip
from pathlib import Path
from statistics import median

INPUT='rs20_source_event_state_machine_candidate_summary_v1_2.csv'
STOCK=Path('common_market_data/minute_1m_stock_v1')
DATE=Path('common_market_data/minute_1m')
OUT='rs20_post_entry_path_diagnostic_v1.csv'
UN='rs20_post_entry_path_unavailable_v1.csv'
SUM='rs20_post_entry_path_summary_v1.txt'
UPS=[1,2,3,4,5,7,10,15,20]
DNS=[1,2,3,4,5,7,10]

def f(x):
    try:return float(str(x).replace(',','').replace('+','').strip())
    except:return None

def a(x):
    v=f(x); return abs(v) if v is not None else None

def code(x):
    s=str(x).strip(); s=s[:-2] if s.endswith('.0') and s[:-2].isdigit() else s; return s.zfill(6)

def read(p):
    with open(p,'r',encoding='utf-8-sig',newline='') as q:return list(csv.DictReader(q))

def write(p,fields,rows):
    with open(p,'w',encoding='utf-8-sig',newline='') as q:
        w=csv.DictWriter(q,fieldnames=fields,extrasaction='ignore'); w.writeheader(); w.writerows(rows)

def loadgz(p):
    d={}
    with gzip.open(p,'rt',encoding='utf-8-sig',newline='') as q:
        for r in csv.DictReader(q):
            t=str(r.get('cntr_tm','')).strip()
            o,h,l,c=a(r.get('open_pric')),a(r.get('high_pric')),a(r.get('low_pric')),a(r.get('cur_prc'))
            if len(t)==14 and t.isdigit() and None not in (o,h,l,c): d[t]={'t':t,'o':o,'h':h,'l':l,'c':c}
    return d

def fallback(base,c,d):
    for p in [base/DATE/d[:4]/d[4:6]/f'{c}_{d}.csv.gz', base/DATE/f'{c}_{d}.csv.gz']:
        if p.exists(): return p

def firstdir(path,e,pct):
    u=e*(1+pct/100); d=e*(1-pct/100)
    for b in path:
        hu=b['h']>=u; hd=b['l']<=d
        if hu and hd:return 'AMBIGUOUS_INTRABAR'
        if hu:return 'UP_FIRST'
        if hd:return 'DOWN_FIRST'
    return 'NONE'

def main():
    base=Path(__file__).resolve().parent; rows=read(base/INPUT)
    exact=[r for r in rows if str(r.get('has_exact_touch_after_activation','')).upper()=='Y']
    fields=['stock_code','stock_name','market','trade_date','event_activation_time','entry_time','entry_price_fib38','core_state_at_entry','bars_after_entry','eod_close','eod_return_pct','mfe_pct','mae_pct','mfe_time','mae_time']
    for x in UPS: fields += [f'hit_plus_{x}pct',f'first_plus_{x}pct_time']
    for x in DNS: fields += [f'hit_minus_{x}pct',f'first_minus_{x}pct_time']
    fields += ['first_direction_1pct','first_direction_2pct','first_direction_3pct','diagnostic_status']
    outs=[]; uns=[]; cache={}
    print('='*82); print('RS20 POST-ENTRY PATH DIAGNOSTIC v1'); print('EXACT TOUCH:',len(exact)); print('LOCAL CACHE ONLY / NO API / NO ORDERS'); print('='*82)
    for i,r in enumerate(exact,1):
        c=code(r.get('stock_code')); d=str(r.get('trade_date','')).strip(); et=str(r.get('first_exact_touch_after_activation_time','')).strip(); e=f(r.get('first_exact_touch_after_activation_fib38'))
        if c not in cache:
            p=base/STOCK/f'{c}.csv.gz'; cache[c]=loadgz(p) if p.exists() else None
        bars=cache[c]
        if not bars or not any(t.startswith(d) for t in bars):
            p=fallback(base,c,d); bars=loadgz(p) if p else None
        if not bars:
            uns.append({'stock_code':c,'stock_name':r.get('stock_name',''),'market':r.get('market',''),'trade_date':d,'reason':'LOCAL_1M_CACHE_NOT_FOUND_FOR_DATE'}); continue
        day=sorted([b for t,b in bars.items() if t.startswith(d)], key=lambda z:z['t'])
        idx=next((j for j,b in enumerate(day) if b['t']==et),None)
        if idx is None or not e:
            uns.append({'stock_code':c,'stock_name':r.get('stock_name',''),'market':r.get('market',''),'trade_date':d,'reason':'ENTRY_TIME_OR_PRICE_NOT_FOUND'}); continue
        path=day[idx+1:]
        o={'stock_code':c,'stock_name':r.get('stock_name',''),'market':r.get('market',''),'trade_date':d,'event_activation_time':r.get('event_activation_time',''),'entry_time':et,'entry_price_fib38':round(e,6),'core_state_at_entry':r.get('core_state_at_first_exact_touch',''),'bars_after_entry':len(path)}
        if not path:
            o.update({'diagnostic_status':'NO_POST_ENTRY_BAR','eod_close':'','eod_return_pct':'','mfe_pct':'','mae_pct':'','mfe_time':'','mae_time':''})
            for x in UPS:o[f'hit_plus_{x}pct']='N';o[f'first_plus_{x}pct_time']=''
            for x in DNS:o[f'hit_minus_{x}pct']='N';o[f'first_minus_{x}pct_time']=''
            for p in [1,2,3]:o[f'first_direction_{p}pct']='NONE'
        else:
            hi=max(path,key=lambda b:b['h']); lo=min(path,key=lambda b:b['l']); close=path[-1]['c']
            o.update({'eod_close':round(close,6),'eod_return_pct':round((close/e-1)*100,6),'mfe_pct':round((hi['h']/e-1)*100,6),'mae_pct':round((lo['l']/e-1)*100,6),'mfe_time':hi['t'],'mae_time':lo['t'],'diagnostic_status':'OK'})
            for x in UPS:
                t=next((b['t'] for b in path if b['h']>=e*(1+x/100)), ''); o[f'hit_plus_{x}pct']='Y' if t else 'N'; o[f'first_plus_{x}pct_time']=t
            for x in DNS:
                t=next((b['t'] for b in path if b['l']<=e*(1-x/100)), ''); o[f'hit_minus_{x}pct']='Y' if t else 'N'; o[f'first_minus_{x}pct_time']=t
            for p in [1,2,3]:o[f'first_direction_{p}pct']=firstdir(path,e,p)
        outs.append(o)
        if i%50==0 or i==len(exact): print(f'[{i}/{len(exact)}] processed {len(outs)} unavailable {len(uns)}')
    write(base/OUT,fields,outs); write(base/UN,['stock_code','stock_name','market','trade_date','reason'],uns)
    valid=[r for r in outs if r['diagnostic_status']=='OK']
    def med(k):
        v=[f(r.get(k)) for r in valid if f(r.get(k)) is not None]; return median(v) if v else None
    lines=['RS20 POST-ENTRY PATH DIAGNOSTIC v1','',f'exact_touch_candidates: {len(exact)}',f'processed: {len(outs)}',f'valid_post_entry_paths: {len(valid)}',f'unavailable: {len(uns)}','',f'median_mfe_pct: {med("mfe_pct")}',f'median_mae_pct: {med("mae_pct")}',f'median_eod_return_pct: {med("eod_return_pct")}','','UP-SIDE HIT DISTRIBUTION (DIAGNOSTIC ONLY)']
    for x in UPS:
        n=sum(r[f'hit_plus_{x}pct']=='Y' for r in valid); lines.append(f'+{x}%: {n}/{len(valid)} ({(n/len(valid)*100 if valid else 0):.2f}%)')
    lines+=['','DOWN-SIDE HIT DISTRIBUTION (DIAGNOSTIC ONLY)']
    for x in DNS:
        n=sum(r[f'hit_minus_{x}pct']=='Y' for r in valid); lines.append(f'-{x}%: {n}/{len(valid)} ({(n/len(valid)*100 if valid else 0):.2f}%)')
    lines+=['','IMPORTANT','- entry reference = first exact Reverse-38 touch from v1.2','- path starts from next 1-minute bar','- percentage thresholds are diagnostics only, NOT source rules','- NOT final win rate/P&L','- NO Kiwoom API / NO orders']
    (base/SUM).write_text('\n'.join(lines)+'\n',encoding='utf-8')
    print('='*82); print('COMPLETE'); print('EXACT TOUCH INPUT      :',len(exact)); print('PROCESSED              :',len(outs)); print('VALID POST-ENTRY PATHS :',len(valid)); print('UNAVAILABLE            :',len(uns)); print('PATH FILE              :',OUT); print('SUMMARY                :',SUM); print('='*82)
if __name__=='__main__': main()
