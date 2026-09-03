# -*- coding: utf-8 -*-
import csv, getpass, os, time
from datetime import datetime
from pathlib import Path
import requests

BASE_URL="https://api.kiwoom.com"
TOKEN_URL=BASE_URL+"/oauth2/token"
CHART_URL=BASE_URL+"/api/dostk/chart"
INPUT_FILE="rs20_full_market_numeric_candidates_v1.csv"
OUT_SUM="rs20_fib38_first_pullback_diagnostic_v2.csv"
OUT_ANCH="rs20_fib38_anchor_detail_v2.csv"
OUT_BARS="rs20_fib38_minute_bars_v2.csv"
last_call=0.0

def sf(v,d=None):
    try:
        if v is None or str(v).strip()=="": return d
        return float(str(v).replace(",","").replace("+","").strip())
    except: return d
def af(v,d=None):
    x=sf(v,d); return abs(x) if x is not None else d
def norm(v):
    s=str(v or "").strip().upper()
    if s.endswith(".0") and s[:-2].isdigit(): s=s[:-2]
    return s.zfill(6) if s.isdigit() else s
def token(app,sec):
    r=requests.post(TOKEN_URL,json={"grant_type":"client_credentials","appkey":app,"secretkey":sec},timeout=20)
    r.raise_for_status(); d=r.json()
    if not d.get("token"): raise RuntimeError("TOKEN fail: "+str(d))
    return d["token"]
def minute_json(tok,code):
    global last_call
    gap=time.monotonic()-last_call
    if gap<0.24: time.sleep(0.24-gap)
    r=requests.post(CHART_URL,headers={"Content-Type":"application/json;charset=UTF-8","authorization":"Bearer "+tok,"api-id":"ka10080"},json={"stk_cd":code,"tic_scope":"1","upd_stkpc_tp":"1"},timeout=30)
    last_call=time.monotonic(); r.raise_for_status(); return r.json()
def parse(x):
    tm=str(x.get("cntr_tm","")).strip()
    if len(tm)!=14 or not tm.isdigit(): return None
    o,h,l,c=af(x.get("open_pric")),af(x.get("high_pric")),af(x.get("low_pric")),af(x.get("cur_prc"))
    if None in (o,h,l,c): return None
    return {"dt":datetime.strptime(tm,"%Y%m%d%H%M%S"),"open":o,"high":h,"low":l,"close":c,"volume":af(x.get("trde_qty"),0.0) or 0.0}
def bars_for(tok,code,date):
    raw=minute_json(tok,code).get("stk_min_pole_chart_qry") or []
    bars=[parse(x) for x in raw]; bars=[b for b in bars if b]
    bars=[b for b in bars if b["dt"].strftime("%Y%m%d")==date]
    u={b["dt"]:b for b in bars}; return [u[k] for k in sorted(u)]
def fib38(h,l): return (h-l)*0.618+l
def dist(b,level):
    if b["low"]<=level<=b["high"]: return 0.0
    if b["low"]>level: return (b["low"]-level)/level*100
    return (level-b["high"])/level*100
def anchors(bars):
    low=lowtm=None; hi=None; out=[]
    for i,b in enumerate(bars):
        if low is None or b["low"]<low:
            low,lowtm,hi=b["low"],b["dt"],b["high"]; continue
        if hi is None or b["high"]>hi:
            hi=b["high"]; level=fib38(hi,low); post=bars[i+1:]
            first=""; md=mdtm=pl=pltm=None
            for p in post:
                d=dist(p,level)
                if md is None or d<md: md,mdtm=d,p["dt"]
                if not first and d==0.0: first=p["dt"].strftime("%Y%m%d%H%M%S")
                if pl is None or p["low"]<pl: pl,pltm=p["low"],p["dt"]
            out.append({"anchor_low_time":lowtm.strftime("%Y%m%d%H%M%S"),"anchor_low":low,"anchor_high_time":b["dt"].strftime("%Y%m%d%H%M%S"),"anchor_high":hi,"wave_rise_from_low_pct":(hi/low-1)*100,"fib38":level,"post_bar_count":len(post),"first_exact_touch_time":first,"min_distance_pct":md,"min_distance_time":mdtm.strftime("%Y%m%d%H%M%S") if mdtm else "","post_low":pl,"post_low_time":pltm.strftime("%Y%m%d%H%M%S") if pltm else ""})
    return out
def save(path,rows,fields):
    with open(path,"w",encoding="utf-8-sig",newline="") as f:
        w=csv.DictWriter(f,fieldnames=fields); w.writeheader()
        for r in rows: w.writerow({k:r.get(k,"") for k in fields})
def main():
    print("="*76); print("Reverse SPES - RS20 Fib38 First Pullback Diagnostic v2")
    print("09:00/self-anchor touch excluded / no invented tolerance / no orders"); print("="*76)
    if not os.path.exists(INPUT_FILE): raise FileNotFoundError(INPUT_FILE+" not found")
    with open(INPUT_FILE,"r",encoding="utf-8-sig",newline="") as f: cand=list(csv.DictReader(f))
    print("Numeric candidates:",len(cand))
    app=getpass.getpass("Kiwoom App Key: "); sec=getpass.getpass("Kiwoom Secret Key: ")
    print("\nTOKEN issuing..."); tok=token(app,sec); print("TOKEN success\n")
    sums=[]; ars=[]; brs=[]
    for n,c in enumerate(cand,1):
        code,name,date=norm(c.get("stock_code")),c.get("stock_name",""),str(c.get("trade_date","")).strip()
        print(f"[{n}/{len(cand)}] {code} {name} {date}")
        bs=bars_for(tok,code,date)
        if not bs:
            sums.append({"stock_code":code,"stock_name":name,"trade_date":date,"status":"NO_MATCHING_MINUTE_DATA","minute_bars":0,"anchor_count":0,"exact_touch_count":0,"best_min_distance_pct":""}); continue
        for b in bs: brs.append({"stock_code":code,"stock_name":name,"trade_date":date,"time":b["dt"].strftime("%Y%m%d%H%M%S"),"open":b["open"],"high":b["high"],"low":b["low"],"close":b["close"],"volume":b["volume"]})
        aa=anchors(bs)
        for seq,a in enumerate(aa,1): ars.append({"stock_code":code,"stock_name":name,"trade_date":date,"anchor_seq":seq,**a,"source_decision":"PENDING_REVIEW"})
        ds=[a["min_distance_pct"] for a in aa if a["min_distance_pct"] is not None]
        exact=sum(bool(a["first_exact_touch_time"]) for a in aa)
        best=min(ds) if ds else None
        sums.append({"stock_code":code,"stock_name":name,"trade_date":date,"status":"DIAGNOSTIC_COMPLETE","minute_bars":len(bs),"anchor_count":len(aa),"exact_touch_count":exact,"best_min_distance_pct":round(best,6) if best is not None else ""})
        print(f"  bars={len(bs)} anchors={len(aa)} exact_after_anchor={exact} best_distance={best}")
    save(OUT_SUM,sums,["stock_code","stock_name","trade_date","status","minute_bars","anchor_count","exact_touch_count","best_min_distance_pct"])
    save(OUT_ANCH,ars,["stock_code","stock_name","trade_date","anchor_seq","anchor_low_time","anchor_low","anchor_high_time","anchor_high","wave_rise_from_low_pct","fib38","post_bar_count","first_exact_touch_time","min_distance_pct","min_distance_time","post_low","post_low_time","source_decision"])
    save(OUT_BARS,brs,["stock_code","stock_name","trade_date","time","open","high","low","close","volume"])
    Path("rs20_fib38_diagnostic_v2_result_note.txt").write_text("v2: anchor high 이후 봉만 눌림 측정. 38선 부근 허용폭/상승률 threshold를 임의 생성하지 않음. 실제 주문 없음.\n",encoding="utf-8")
    print("\nDone"); print(OUT_SUM); print(OUT_ANCH); print(OUT_BARS)
if __name__=="__main__": main()
