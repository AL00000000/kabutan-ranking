import csv, io, math, json, datetime as dt

def rdcp932(p):
    return open(p,'rb').read().decode('cp932',errors='replace').splitlines()

def parse_nomura(path, skip=4, cols=(1,2)):
    """returns dict date->(price, total)"""
    out={}
    for line in rdcp932(path)[skip:]:
        f=line.split(',')
        if len(f)<3 or not f[0].strip().isdigit(): continue
        d=dt.date(int(f[0][:4]),int(f[0][4:6]),int(f[0][6:8]))
        try: out[d]=(float(f[cols[0]]), float(f[cols[1]]))
        except: pass
    return out

def parse_nikkei_monthly(path):
    out={}
    for line in rdcp932(path)[1:]:
        f=[x.strip().strip('"') for x in line.split(',')]
        if len(f)<7 or '/' not in f[0]: continue
        y,m,_=f[0].split('/')
        d=dt.date(int(y),int(m),1)
        try: out[d]=(float(f[1]), float(f[5]))
        except: pass
    return out

def parse_rn_monthly(path):
    lines=open(path,'rb').read().decode('cp932',errors='replace').splitlines()
    hdr=lines[2].split(',')
    names=[h.strip() for h in hdr[1:]]
    out={}
    for line in lines[3:]:
        f=line.split(',')
        if len(f)<2 or not f[0].strip().isdigit(): continue
        ym=f[0].strip(); d=dt.date(int(ym[:4]),int(ym[4:6]),1)
        row={}
        for n,v in zip(names,f[1:]):
            v=v.strip()
            if v and v!='nan':
                try: row[n]=float(v)
                except: pass
        out[d]=row
    return out, names

nhdiv = parse_nomura('nhdiv_daily.csv')
nhdivd= parse_nomura('nhdivd.csv')
smart = parse_nomura('smart50.csv')
nkhdy = parse_nikkei_monthly('nkhdy_monthly.csv')
rn, rn_names = parse_rn_monthly('rn_mt.csv')

print('nhdiv70 :', min(nhdiv), max(nhdiv), nhdiv[max(nhdiv)])
print('nhdivd  :', min(nhdivd), max(nhdivd), nhdivd[max(nhdivd)])
print('smart50 :', min(smart), max(smart), smart[max(smart)])
print('nk hdy50:', min(nkhdy), max(nkhdy), nkhdy[max(nkhdy)])
print('RN      :', min(rn), max(rn))
print('RN cols :', rn_names[:8])

# ---- monthly series builders ----
def to_monthly(daily, idx):
    """daily: dict date->tuple ; idx: which element. returns dict (y,m)->value using last obs in month"""
    best={}
    for d,v in daily.items():
        k=(d.year,d.month)
        if k not in best or d>best[k][0]: best[k]=(d,v[idx])
    return {k:v[1] for k,v in best.items()}

S={}
S['野村高配当70(配当込)']   = to_monthly(nhdiv,1)
S['野村高配当70(配当なし)'] = to_monthly(nhdiv,0)
S['野村高配当70配当加重(込)']= to_monthly(nhdivd,1)
S['野村高配当SMART50(込)']  = to_monthly(smart,1)
S['日経高配当50(配当込)']   = {(d.year,d.month):v[1] for d,v in nkhdy.items()}
S['日経高配当50(配当なし)'] = {(d.year,d.month):v[0] for d,v in nkhdy.items()}
for col in ['Total Market','Total Market Value','Large','Large Value','Small','Small Value','Top','Top Value','Small Core']:
    S['RN '+col] = {(d.year,d.month):r[col] for d,r in rn.items() if col in r}

def stats(series, start=None, end=None):
    ks=sorted(series)
    if start: ks=[k for k in ks if k>=start]
    if end:   ks=[k for k in ks if k<=end]
    if len(ks)<13: return None
    vals=[series[k] for k in ks]
    n=len(ks)-1
    yrs=n/12
    mult=vals[-1]/vals[0]
    cagr=mult**(1/yrs)-1
    rets=[vals[i+1]/vals[i]-1 for i in range(n)]
    mean=sum(rets)/n
    var=sum((r-mean)**2 for r in rets)/(n-1)
    vol=math.sqrt(var)*math.sqrt(12)
    peak=vals[0]; mdd=0
    for v in vals:
        peak=max(peak,v); mdd=min(mdd, v/peak-1)
    return dict(start=ks[0],end=ks[-1],years=yrs,mult=mult,cagr=cagr,vol=vol,mdd=mdd,
                sharpe=cagr/vol if vol else None)

def show(names, start, end, title):
    print('\n### '+title)
    print(f"{'指数':<26}{'期間':<18}{'倍率':>9}{'年率':>8}{'年率変動':>9}{'最大DD':>9}{'R/R':>7}")
    for nm in names:
        st=stats(S[nm],start,end)
        if not st: print(f'{nm:<26} データ不足'); continue
        p=f"{st['start'][0]}/{st['start'][1]:02d}-{st['end'][0]}/{st['end'][1]:02d}"
        print(f"{nm:<26}{p:<18}{st['mult']:>8.2f}x{st['cagr']*100:>7.2f}%{st['vol']*100:>8.1f}%{st['mdd']*100:>8.1f}%{st['sharpe']:>7.2f}")

END=(2026,8)
show(['野村高配当70(配当込)','日経高配当50(配当込)','RN Total Market','RN Total Market Value','RN Large','RN Small'],
     (2001,12),END,'共通期間 2001年12月末 → 2026年8月末 (24.7年, 配当込み)')
show(['野村高配当70(配当込)','野村高配当70配当加重(込)','RN Total Market','RN Total Market Value','RN Large','RN Small'],
     (2000,12),END,'2000年12月末 → 2026年8月末 (25.7年, 配当込み)')
show(['野村高配当70(配当込)','日経高配当50(配当込)','野村高配当SMART50(込)','RN Total Market','RN Small'],
     (2008,1),END,'2008年1月末 → 2026年8月末 (18.6年, 配当込み)')
show(['RN Total Market','RN Total Market Value','RN Large','RN Large Value','RN Small','RN Small Value','RN Top','RN Top Value'],
     (1996,8),END,'参考: 過去30年 1996年8月末 → 2026年8月末 (配当込み)')
show(['RN Total Market','RN Total Market Value','RN Large','RN Large Value','RN Small','RN Small Value'],
     (1979,12),END,'参考: 全期間 1979年12月末 → 2026年8月末 (46.7年, 配当込み)')

print('\n\n======== 遡及算出期間 vs 実算出期間 ========')
show(['野村高配当70(配当込)','日経高配当50(配当込)','RN Total Market'],(2001,12),(2016,12),'遡及/過去期間 2001/12-2016/12')
show(['野村高配当70(配当込)','日経高配当50(配当込)','野村高配当SMART50(込)','RN Total Market'],(2016,12),END,'実算出期間 2016/12-2026/08 (日経は2017/01公表開始)')

print('\n\n======== 年次リターン (%) ========')
names=['野村高配当70(配当込)','日経高配当50(配当込)','RN Total Market','RN Small']
print(f"{'年':<6}"+''.join(f'{n[:14]:>16}' for n in names))
tot={n:[] for n in names}
for y in range(2001,2027):
    row=f'{y:<6}'
    for n in names:
        s=S[n]
        a=s.get((y-1,12)); 
        b=s.get((y,12)) if y<2026 else s.get((2026,8))
        if a and b:
            r=(b/a-1)*100; row+=f'{r:>15.1f}%'; tot[n].append(r)
        else: row+=f'{"-":>16}'
    print(row + ('  ※8月末まで' if y==2026 else ''))

print('\n\n======== 最大ドローダウンの中身 ========')
for n in ['野村高配当70(配当込)','日経高配当50(配当込)','RN Total Market']:
    s=S[n]; ks=sorted(k for k in s if k>=(2001,12) and k<=END)
    peak=-1; pk=None; mdd=0; info=None
    for k in ks:
        v=s[k]
        if v>peak: peak=v; pk=k
        dd=v/peak-1
        if dd<mdd: mdd=dd; info=(pk,k)
    # recovery
    rec=None
    if info:
        pv=s[info[0]]
        for k in ks:
            if k>info[1] and s[k]>=pv: rec=k; break
    print(f'{n:<24} {mdd*100:6.1f}%  {info[0][0]}/{info[0][1]:02d} -> {info[1][0]}/{info[1][1]:02d}  回復: {rec[0] if rec else "未"}/{rec[1]:02d}' if rec else f'{n:<24} {mdd*100:6.1f}%  {info[0][0]}/{info[0][1]:02d} -> {info[1][0]}/{info[1][1]:02d}  回復:未')

print('\n\n======== 株価のみ / 配当込み / 税引後 ========')
nh_net = parse_nomura('nhdiv_daily.csv', cols=(0,5))   # col5 = 配当課税考慮済、居住者
S['野村高配当70(税引後)'] = to_monthly(nh_net,1)
S['日経高配当50(税引後)'] = {(d.year,d.month):v for d,v in
    {dt.date(int(l.split(',')[0].strip('\"').split('/')[0]),int(l.split(',')[0].strip('\"').split('/')[1]),1):float(l.split(',')[6].strip('\"'))
     for l in rdcp932('nkhdy_monthly.csv')[1:] if '/' in l.split(',')[0] and len(l.split(','))>6}.items()}

for label,trio in [('野村高配当70 (全上場・均等・四半期入替)',
                    ['野村高配当70(配当なし)','野村高配当70(配当込)','野村高配当70(税引後)']),
                   ('日経高配当株50 (日経225内=超大型・利回りW・年1入替)',
                    ['日経高配当50(配当なし)','日経高配当50(配当込)','日経高配当50(税引後)'])]:
    print('\n--- '+label)
    for n in trio:
        st=stats(S[n],(2001,12),END)
        if st: print(f"  {n:<24} {st['mult']:>7.2f}x  年率 {st['cagr']*100:>6.2f}%")

print('\n--- ベンチマーク (RN Total Market 配当込み) 同期間')
st=stats(S['RN Total Market'],(2001,12),END); print(f"  {st['mult']:>7.2f}x  年率 {st['cagr']*100:>6.2f}%")

print('\n\n======== ローリング10年 年率リターン (配当込み) ========')
print(f"{'開始':<9}{'野村70':>10}{'日経HDY50':>11}{'市場':>9}{'差(野村)':>10}{'差(日経)':>10}")
for y in range(2001,2017):
    k0=(y,12); k1=(y+10,12) if y+10<=2025 else (2026,8)
    out=[]
    for n in ['野村高配当70(配当込)','日経高配当50(配当込)','RN Total Market']:
        s=S[n]
        if k0 in s and k1 in s:
            yrs=((k1[0]-k0[0])*12+(k1[1]-k0[1]))/12
            out.append(((s[k1]/s[k0])**(1/yrs)-1)*100)
        else: out.append(None)
    if None in out: continue
    print(f"{y}/12{'':<4}{out[0]:>9.1f}%{out[1]:>10.1f}%{out[2]:>8.1f}%{out[0]-out[2]:>9.1f}%{out[1]-out[2]:>9.1f}%")

print('\n\n======== 100万円が幾らになったか (2001年12月末→2026年8月末, 配当込み) ========')
for n in ['野村高配当70(配当込)','日経高配当50(配当込)','RN Total Market','RN Total Market Value','RN Small']:
    st=stats(S[n],(2001,12),END); print(f'  {n:<24} {st["mult"]*100:>9,.0f}万円')
print('\n  税引後(20.315%源泉)')
for n in ['野村高配当70(税引後)','日経高配当50(税引後)']:
    st=stats(S[n],(2001,12),END); print(f'  {n:<24} {st["mult"]*100:>9,.0f}万円')

print('\n======== サイズ効果(バリュー内) RN Large Value vs Small Value ========')
for per,lab in [((1979,12),'46.7年'),((1996,8),'30年'),((2001,12),'24.7年'),((2016,12),'9.7年')]:
    a=stats(S['RN Large Value'],per,END); b=stats(S['RN Small Value'],per,END)
    c=stats(S['RN Top Value'],per,END)
    print(f'  {lab:<7} Large Value {a["cagr"]*100:5.2f}%  /  Small Value {b["cagr"]*100:5.2f}%  /  Top(超大型)Value {c["cagr"]*100:5.2f}%   差(S-L) {(b["cagr"]-a["cagr"])*100:+.2f}%')

print('\n======== 売買コスト控除後の年率 (24.7年, 配当込み) ========')
base={'野村高配当70':10.97,'日経高配当50':13.77}
print(f"{'':<14}{'コスト0':>9}{'0.3%':>8}{'0.7%':>8}{'1.5%':>8}  ← 年間コスト(回転率に比例)")
for k,v in base.items():
    print(f'{k:<14}{v:>8.2f}%'+''.join(f'{v-c:>7.2f}%' for c in [0.3,0.7,1.5]))
print(f'{"市場(RN TM)":<14}{8.14:>8.2f}%')

# ---- export for chart ----
export={}
keys=[k for k in sorted(S['日経高配当50(配当込)']) if k>=(2001,12) and k<=END]
for nm,key in [('nomura70','野村高配当70(配当込)'),('nikkei50','日経高配当50(配当込)'),
               ('market','RN Total Market'),('value','RN Total Market Value'),('small','RN Small'),
               ('nomura70_px','野村高配当70(配当なし)'),('nikkei50_px','日経高配当50(配当なし)')]:
    s=S[key]; base=s[(2001,12)]
    export[nm]=[round(s[k]/base,4) if k in s else None for k in keys]
export['dates']=[f'{y}-{m:02d}' for y,m in keys]
annual={}
for nm,key in [('nomura70','野村高配当70(配当込)'),('nikkei50','日経高配当50(配当込)'),('market','RN Total Market')]:
    s=S[key]; arr=[]
    for y in range(2002,2027):
        a=s.get((y-1,12)); b=s.get((y,12)) if y<2026 else s.get((2026,8))
        arr.append(round((b/a-1)*100,1) if a and b else None)
    annual[nm]=arr
annual['years']=list(range(2002,2027))
export['annual']=annual
roll=[]
for y in range(2001,2017):
    k0=(y,12); k1=(y+10,12) if y+10<=2025 else (2026,8)
    r={}
    for nm,key in [('nomura70','野村高配当70(配当込)'),('nikkei50','日経高配当50(配当込)'),('market','RN Total Market')]:
        s=S[key]; yrs=((k1[0]-k0[0])*12+(k1[1]-k0[1]))/12
        r[nm]=round(((s[k1]/s[k0])**(1/yrs)-1)*100,2)
    r['start']=y; roll.append(r)
export['rolling']=roll
json.dump(export, open('chartdata.json','w'), ensure_ascii=False)
print('exported', len(keys),'months')
