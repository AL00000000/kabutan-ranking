exec(open('analyze.py',encoding='utf-8').read().split('# ---- export for chart ----')[0])

import datetime as dt, json, math
# ---- Nikkei 225 price (Yahoo, JST-aligned; verified vs official daily: max diff 0.0 over 45 months) ----
yj=json.load(open('n225_y2.json'))['chart']['result'][0]
ts=yj['timestamp']; cl=yj['indicators']['quote'][0]['close']
nk225={}
for t,c in zip(ts,cl):
    if c is None: continue
    d=dt.datetime.utcfromtimestamp(t+9*3600)
    nk225[(d.year,d.month)]=c
S['日経平均(株価)']=nk225

# ---- Nikkei 225 total return (official, 2016-01 only) ----
nk225tr={}
for line in rdcp932('nk225tr_m.csv')[1:]:
    f=[x.strip().strip('"') for x in line.split(',')]
    if len(f)<2 or '/' not in f[0]: continue
    y,m,_=f[0].split('/')
    try: nk225tr[(int(y),int(m))]=float(f[1])
    except: pass
S['日経平均(配当込)']=nk225tr

print('日経平均 株価   :', min(S['日経平均(株価)']), '->', max(S['日経平均(株価)']), f"{S['日経平均(株価)'][(2026,8)]:,.2f}")
print('日経平均 配当込 :', min(S['日経平均(配当込)']), '->', max(S['日経平均(配当込)']))

print('\n### 各系列の実データ範囲')
print(f"{'系列':<26}{'最古':>10}{'最新':>10}{'月数':>7}")
for n in ['日経高配当50(配当込)','日経高配当50(配当なし)','野村高配当70(配当込)','野村高配当70(配当なし)',
          '野村高配当SMART50(込)','日経平均(株価)','日経平均(配当込)','RN Total Market','RN Large','RN Top']:
    ks=sorted(S[n]); print(f'{n:<26}{ks[0][0]}/{ks[0][1]:02d}{ks[-1][0]:>7}/{ks[-1][1]:02d}{len(ks):>7}')

END=(2026,8)
print('\n\n### 【株価のみ・配当を含まない】共通期間 2001/12末→2026/8末 (24.7年)')
show(['日経高配当50(配当なし)','野村高配当70(配当なし)','日経平均(株価)'],(2001,12),END,'全て配当なしベース（同一土俵）')

print('\n### 【配当込み】共通期間 2001/12末→2026/8末 (24.7年)')
show(['日経高配当50(配当込)','野村高配当70(配当込)','RN Top','RN Large','RN Total Market'],(2001,12),END,'配当込み（日経平均TRはこの期間の公表データなし→RN大型/超大型で代替）')

print('\n### 【配当込み】日経平均TRが公表されている期間 2016/1末→2026/8末 (10.6年)')
show(['日経高配当50(配当込)','野村高配当70(配当込)','野村高配当SMART50(込)','日経平均(配当込)','RN Total Market'],(2016,1),END,'')

print('\n### 日経平均の配当寄与（実測, 2016/1→2026/8）')
a=stats(S['日経平均(株価)'],(2016,1),END); b=stats(S['日経平均(配当込)'],(2016,1),END)
print(f'  株価のみ {a["cagr"]*100:.2f}%  /  配当込み {b["cagr"]*100:.2f}%  → 配当寄与 +{(b["cagr"]-a["cagr"])*100:.2f}%/年')
a=stats(S['日経高配当50(配当なし)'],(2016,1),END); b=stats(S['日経高配当50(配当込)'],(2016,1),END)
print(f'  [参考] 高配当50 株価のみ {a["cagr"]*100:.2f}% / 配当込み {b["cagr"]*100:.2f}% → 配当寄与 +{(b["cagr"]-a["cagr"])*100:.2f}%/年')

print('\n\n### 各系列を「自分の全期間」で見た場合（期間がバラバラなので直接比較不可）')
for n in ['日経高配当50(配当込)','野村高配当70(配当込)','野村高配当SMART50(込)','日経平均(株価)','RN Total Market']:
    ks=sorted(S[n]); st=stats(S[n],ks[0],END)
    print(f'  {n:<24} {ks[0][0]}/{ks[0][1]:02d}→2026/08 ({st["years"]:.1f}年)  年率 {st["cagr"]*100:>6.2f}%  {st["mult"]:>7.2f}倍')

print('\n\n### 長期(日経平均が使える範囲) 1984/12→2026/08')
show(['日経平均(株価)','RN Total Market','RN Large','RN Top','RN Total Market Value'],(1984,12),END,'41.7年 ※日経平均のみ配当なし、RNは配当込み')

# ================= export v2 =================
keys=[k for k in sorted(S['日経高配当50(配当込)']) if k>=(2001,12) and k<=END]
ex={'dates':[f'{y}-{m:02d}' for y,m in keys]}
def ser(key):
    s=S[key]; b=s[(2001,12)]
    return [round(s[k]/b,4) if k in s else None for k in keys]
for nm,key in [('hdy_tr','日経高配当50(配当込)'),('n70_tr','野村高配当70(配当込)'),
               ('mkt_tr','RN Total Market'),('large_tr','RN Large'),
               ('hdy_px','日経高配当50(配当なし)'),('n70_px','野村高配当70(配当なし)'),
               ('n225_px','日経平均(株価)')]:
    ex[nm]=ser(key)
# 2016-01 based block (incl Nikkei TR)
k2=[k for k in sorted(S['日経平均(配当込)']) if k>=(2016,1) and k<=END]
ex['dates2']=[f'{y}-{m:02d}' for y,m in k2]
for nm,key in [('hdy2','日経高配当50(配当込)'),('n702','野村高配当70(配当込)'),
               ('n2252','日経平均(配当込)'),('mkt2','RN Total Market'),('sm502','野村高配当SMART50(込)')]:
    s=S[key]; b=s[(2016,1)]
    ex[nm]=[round(s[k]/b,4) if k in s else None for k in k2]
ann={'years':list(range(2002,2027))}
for nm,key in [('hdy','日経高配当50(配当込)'),('n70','野村高配当70(配当込)'),
               ('mkt','RN Total Market'),('n225','日経平均(株価)')]:
    s=S[key]; arr=[]
    for y in ann['years']:
        a=s.get((y-1,12)); b=s.get((y,12)) if y<2026 else s.get((2026,8))
        arr.append(round((b/a-1)*100,1) if a and b else None)
    ann[nm]=arr
ex['annual']=ann
roll=[]
for y in range(2001,2017):
    k0=(y,12); k1=(y+10,12) if y+10<=2025 else (2026,8)
    r={'start':y}
    for nm,key in [('hdy','日経高配当50(配当込)'),('n70','野村高配当70(配当込)'),
                   ('mkt','RN Total Market'),('n225','日経平均(株価)')]:
        s=S[key]; yrs=((k1[0]-k0[0])*12+(k1[1]-k0[1]))/12
        r[nm]=round(((s[k1]/s[k0])**(1/yrs)-1)*100,2)
    roll.append(r)
ex['rolling']=roll
json.dump(ex,open('chartdata2.json','w'),ensure_ascii=False)
print('\nexport v2:', len(keys),'months /', len(k2),'months(2016-)')
print('checks: n225_px last', ex['n225_px'][-1], 'hdy_px last', ex['hdy_px'][-1], 'n70_px last', ex['n70_px'][-1])
print('2016block last:', {k:ex[k][-1] for k in ['hdy2','n702','n2252','mkt2']})
print('nulls:', {k:sum(1 for x in v if x is None) for k,v in ex.items() if isinstance(v,list) and k.startswith(('hdy','n70','mkt','n225','large','sm50'))})
