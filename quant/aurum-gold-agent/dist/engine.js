(function(root){
'use strict';
const VERSION='0.2.0';
const FACTOR_DEFS=[['mom5','5日动量'],['mom20','20日动量'],['reversal5','5日反转'],['vol20','20日低波动'],['volumeSurprise','20日量能异常'],['amihud','Amihud流动性近似'],['range','日内振幅'],['clv','收盘位置'],['sentiment','舆情净分'],['newsAttention','新闻关注度']];
const positive=['上涨','利好','增持','回暖','降息','宽松','避险','买入','流入','突破','增长','走强','bullish','inflow','rally'];
const negative=['下跌','利空','减持','抛售','加息','紧缩','卖出','流出','跌破','下降','走弱','bearish','outflow','selloff'];
const mean=a=>a.length?a.reduce((s,v)=>s+v,0)/a.length:null;
const sd=a=>a.length>1?Math.sqrt(a.reduce((s,v)=>s+(v-mean(a))**2,0)/(a.length-1)):0;
const finite=v=>typeof v==='number'&&Number.isFinite(v);
function csvRows(text){
  if(typeof text!=='string')throw Error('CSV内容必须是文本');
  text=text.replace(/^\uFEFF/,'');let rows=[],row=[],field='',quote=false;
  for(let i=0;i<text.length;i++){
    let c=text[i];if(c==='"'){if(quote&&text[i+1]==='"'){field+='"';i++;}else quote=!quote;}
    else if(c===','&&!quote){row.push(field.trim());field='';}
    else if((c==='\n'||c==='\r')&&!quote){if(c==='\r'&&text[i+1]==='\n')i++;row.push(field.trim());if(row.some(Boolean))rows.push(row);row=[];field='';}
    else field+=c;
  }
  if(quote)throw Error('CSV引号未闭合');row.push(field.trim());if(row.some(Boolean))rows.push(row);
  if(rows.length<2)throw Error('CSV需要表头和数据行');
  const heads=rows.shift().map(x=>x.toLowerCase().replace(/\s/g,''));
  if(new Set(heads).size!==heads.length)throw Error('CSV表头重复');
  return rows.map((r,i)=>{if(r.length!==heads.length)throw Error(`CSV第${i+2}行列数不一致`);return Object.fromEntries(heads.map((h,j)=>[h,r[j]]));});
}
function field(r,...keys){for(let k of keys)if(r[k]!==undefined&&r[k]!=='')return r[k];return undefined;}
function isoDate(value){
  if(typeof value!=='string')throw Error('缺少日期');
  let s=value.trim().replace(/\//g,'-');if(/^\d{8}$/.test(s))s=s.slice(0,4)+'-'+s.slice(4,6)+'-'+s.slice(6);
  const m=s.match(/^(\d{4})-(\d{1,2})-(\d{1,2})(?:[ T].*)?$/);if(!m)throw Error('日期格式无效：'+value);
  let d=`${m[1]}-${m[2].padStart(2,'0')}-${m[3].padStart(2,'0')}`;
  let dt=new Date(d+'T00:00:00Z');if(!Number.isFinite(+dt)||dt.toISOString().slice(0,10)!==d)throw Error('日期不存在：'+value);
  return d;
}
function attach(array,provenance){Object.defineProperty(array,'provenance',{value:Object.freeze(provenance),enumerable:false});return array;}
function parsePrices(text,provenance={}){
  const seen=new Set(),rows=csvRows(text).map((r,i)=>{
    let date=isoDate(field(r,'date','日期','交易日期','时间'));
    let symbol=String(field(r,'symbol','代码','证券代码','股票代码')||'USER_ETF');
    let b={date,symbol};
    for(let [k,zh] of [['open','开盘'],['high','最高'],['low','最低'],['close','收盘'],['volume','成交量']]){
      b[k]=Number(field(r,k,zh,zh+'价'));if(!finite(b[k])||b[k]<=0)throw Error(`第${i+2}行 ${k} 必须是有限正数`);
    }
    let rawAmount=field(r,'amount','成交额');b.amount=rawAmount===undefined?null:Number(rawAmount);
    if(rawAmount!==undefined&&(!finite(b.amount)||b.amount<=0))throw Error(`第${i+2}行成交额无效`);
    if(b.high<Math.max(b.open,b.close,b.low)||b.low>Math.min(b.open,b.close,b.high))throw Error(`第${i+2}行OHLC不满足最高/最低约束`);
    const key=date+'|'+symbol;if(seen.has(key))throw Error('日期/代码重复：'+key);seen.add(key);return b;
  }).sort((a,b)=>a.date.localeCompare(b.date)||a.symbol.localeCompare(b.symbol));
  return attach(rows,{source:provenance.source||'用户CSV（来源未独立核验）',synthetic:provenance.synthetic===true,priceBasis:provenance.priceBasis||'用户声明口径；请核对复权',volumeUnit:provenance.volumeUnit||'原CSV单位，未转换',importedAt:new Date().toISOString()});
}
function sentiment(title){let s=0,t=title.toLowerCase();for(let w of positive)if(t.includes(w))s++;for(let w of negative)if(t.includes(w))s--;return s?Math.max(-1,Math.min(1,s/3)):0;}
function parseNews(text){
  const seen=new Set();let out=[];
  for(const [i,r] of csvRows(text).entries()){
    const title=field(r,'title','标题','新闻标题');if(!title)throw Error(`新闻第${i+2}行缺少标题`);
    const raw=field(r,'published_at','发布时间','时间','date','日期');let day=isoDate(raw);
    const key=title.replace(/\s/g,'').toLowerCase();if(seen.has(key))continue;seen.add(key);
    const supplied=field(r,'sentiment','情绪分数','score');let score=supplied===undefined?sentiment(title):Number(supplied);
    if(!finite(score)||Math.abs(score)>1)throw Error('舆情分数必须在[-1,1]内');
    const url=field(r,'url','原文链接','link')||'';if(url&&!/^https?:\/\//i.test(url))throw Error('新闻原文链接必须是http或https地址');
    out.push({published_at:raw,date:day,title,url,source:field(r,'source','来源')||'用户导入',sentiment:score,scoring:supplied===undefined?'关键词启发式':'用户给定分数'});
  }
  return out.sort((a,b)=>a.date.localeCompare(b.date));
}
function newsFeatures(bars,news){
  let daily=bars.map(b=>({date:b.date,count:0,sentiment:0,items:[]}));
  for(let item of news){let dt=new Date(isoDate(item.date||item.published_at)+'T00:00:00Z');dt.setUTCDate(dt.getUTCDate()+1);let available=dt.toISOString().slice(0,10);let i=bars.findIndex(b=>b.date>=available);if(i<0)continue;
    daily[i].count++;daily[i].sentiment+=item.sentiment;daily[i].items.push({...item,available_from:available});
  }
  for(let d of daily)d.sentiment=d.count?d.sentiment/d.count:0;return daily;
}
function ranks(a){let idx=a.map((v,i)=>i).sort((i,j)=>a[i]-a[j]),r=Array(a.length);for(let i=0;i<idx.length;){let end=i+1;while(end<idx.length&&a[idx[end]]===a[idx[i]])end++;for(let k=i;k<end;k++)r[idx[k]]=(i+end-1)/2;i=end;}return r;}
function corr(a,b){if(a.length<3)return null;let ma=mean(a),mb=mean(b),va=a.reduce((s,x)=>s+(x-ma)**2,0),vb=b.reduce((s,x)=>s+(x-mb)**2,0);return va&&vb?a.reduce((s,x,i)=>s+(x-ma)*(b[i]-mb),0)/Math.sqrt(va*vb):null;}
function featureValues(bars,daily){
 let f=Object.fromEntries(FACTOR_DEFS.map(([k])=>[k,Array(bars.length).fill(null)]));
 for(let t=0;t<bars.length;t++){let b=bars[t];f.range[t]=(b.high-b.low)/b.close;f.clv[t]=b.high===b.low?0:(2*b.close-b.high-b.low)/(b.high-b.low);
   f.sentiment[t]=daily[t].count?daily[t].sentiment:null;f.newsAttention[t]=daily[t].count?daily[t].count:null;
   if(t>=5){f.mom5[t]=b.close/bars[t-5].close-1;f.reversal5[t]=-f.mom5[t];}
   if(t>=20){let returns=bars.slice(t-19,t+1).map((x,k)=>x.close/bars[t-20+k].close-1);
     f.mom20[t]=b.close/bars[t-20].close-1;f.vol20[t]=-sd(returns);
     f.volumeSurprise[t]=b.volume/mean(bars.slice(t-20,t).map(x=>x.volume))-1;
     f.amihud[t]=-mean(bars.slice(t-19,t+1).map((x,k)=>Math.abs(returns[k])/(x.amount||x.close*x.volume)));
   }
 }return f;
}
function ic(values,bars,start,end){let a=[],b=[];for(let t=start;t+2<end;t++)if(finite(values[t])){a.push(values[t]);b.push(bars[t+2].close/bars[t+1].close-1);}return {pearson:corr(a,b),spearman:corr(ranks(a),ranks(b)),samples:a.length};}
function ema(a,period){let alpha=2/(period+1),last=a[0];return a.map(x=>(last=last+alpha*(x-last)));}
function chan(bars){
  if(!bars.length)return {merged:[],fractals:[],strokes:[],centers:[],divergences:[],rule:'简化规则，不等同于完整缠论'};
  let merged=[];
  for(let i=0;i<bars.length;i++){
    let b={...bars[i],startIndex:i,endIndex:i,startDate:bars[i].date,endDate:bars[i].date};let p=merged.at(-1),prev=merged.at(-2);
    if(p&&((b.high<=p.high&&b.low>=p.low)||(b.high>=p.high&&b.low<=p.low))){let up=prev?p.high>=prev.high:b.close>=p.close;
      p.high=up?Math.max(p.high,b.high):Math.min(p.high,b.high);p.low=up?Math.max(p.low,b.low):Math.min(p.low,b.low);p.close=b.close;p.endIndex=i;p.endDate=b.date;p.volume+=b.volume;
    }else merged.push(b);
  }
  const fractals=[];for(let i=1;i<merged.length-1;i++){
    let [a,b,c]=merged.slice(i-1,i+2),top=b.high>a.high&&b.high>c.high&&b.low>a.low&&b.low>c.low,bot=b.low<a.low&&b.low<c.low&&b.high<a.high&&b.high<c.high;
    if(top||bot)fractals.push({type:top?'top':'bottom',date:b.endDate,index:b.endIndex,mergedIndex:i,price:top?b.high:b.low,confirmedAt:c.endDate,confirmedIndex:c.endIndex});
  }
  // Rightmost merged candle can still expand. Confirm only when its successor
  // starts: use the next merged bar as a conservative immutability witness.
  const confirmed=fractals.filter(x=>x.mergedIndex+2<merged.length).map(x=>({...x,confirmedAt:merged[x.mergedIndex+2].startDate,confirmedIndex:merged[x.mergedIndex+2].startIndex}));
  let points=[];for(let f of confirmed){let p=points.at(-1);if(!p){points.push(f);continue;}
    if(f.type===p.type){if((f.type==='top'&&f.price>p.price)||(f.type==='bottom'&&f.price<p.price))points[points.length-1]=f;}
    else if(f.mergedIndex-p.mergedIndex>=4&&((f.type==='top'&&f.price>p.price)||(f.type==='bottom'&&f.price<p.price)))points.push(f);
  }
  let strokes=[];for(let i=1;i<points.length;i++){let a=points[i-1],b=points[i];strokes.push({start:a,end:b,startDate:a.date,endDate:b.date,low:Math.min(a.price,b.price),high:Math.max(a.price,b.price),direction:b.type==='top'?'up':'down',confirmedAt:b.confirmedAt,confirmedIndex:b.confirmedIndex});}
  let centers=[];for(let i=2;i<strokes.length;i++){let ss=strokes.slice(i-2,i+1),low=Math.max(...ss.map(s=>s.low)),high=Math.min(...ss.map(s=>s.high));if(high>low)centers.push({startDate:ss[0].startDate,endDate:ss[2].endDate,low,high,confirmedAt:ss[2].confirmedAt,confirmedIndex:ss[2].confirmedIndex});}
  let fast=ema(bars.map(b=>b.close),12),slow=ema(bars.map(b=>b.close),26),dif=fast.map((x,i)=>x-slow[i]),dea=ema(dif,9),hist=dif.map((x,i)=>2*(x-dea[i]));
  let divergences=[];for(let i=2;i<strokes.length;i++){let a=strokes[i-2],b=strokes[i];if(a.direction!==b.direction)continue;
    let area=s=>hist.slice(s.start.index,s.end.index+1).reduce((sum,x)=>sum+Math.abs(x),0);
    if(((b.direction==='up'&&b.end.price>a.end.price)||(b.direction==='down'&&b.end.price<a.end.price))&&area(b)<area(a))divergences.push({date:b.endDate,type:b.direction==='up'?'顶背驰候选':'底背驰候选',confirmedAt:b.confirmedAt,confirmedIndex:b.confirmedIndex,priorArea:area(a),area:area(b),heuristic:true});
  }
  return {merged,fractals:confirmed,strokes,centers,divergences,macd:hist,rule:'包含处理；三根合并K线分型并等待右侧K线封闭；端点间至少5根合并K线；三笔交集；MACD面积背驰候选。末端笔可能被后续同类极值更新。'};
}
function metrics(returns){let nav=1,peak=1,dd=0;for(let r of returns){nav*=1+r;peak=Math.max(peak,nav);dd=Math.min(dd,nav/peak-1);}let vol=sd(returns);return {totalReturn:nav-1,annualReturn:returns.length?nav**(252/returns.length)-1:0,volatility:vol*Math.sqrt(252),sharpe:vol?mean(returns)/vol*Math.sqrt(252):null,maxDrawdown:dd,intervals:returns.length};}
function backtest(bars,factors,selected,directions,split,cost){
 let nav=100000,bnav=100000,pos=0,ledger=[],equity=[],returns=[],benchmarkReturns=[],peak=100000,turnover=0;
 for(let t=split;t<bars.length-1;t++){
   let raw=selected.map(k=>{let vals=factors[k].slice(0,split).filter(finite);if(!vals.length||!finite(factors[k][t-1]))return null;let scale=sd(vals);return scale?directions[k]*(factors[k][t-1]-mean(vals))/scale:0;}).filter(finite);
   let score=raw.length?mean(raw):null,target=score!==null&&score>0?1:0,before=nav,bbefore=bnav;
   if(target!==pos){let notional=target?nav/(1+cost):nav,charge=notional*cost;nav=target?notional:nav-charge;turnover+=notional;ledger.push({date:bars[t].date,signalDate:bars[t-1].date,side:target?'BUY':'SELL',price:bars[t].close,notional,cost:charge,targetWeight:target,researchOnly:true});pos=target;}
   if(t===split)bnav/=1+cost;
   let ratio=bars[t+1].close/bars[t].close;nav*=pos?ratio:1;bnav*=ratio;
   if(t===bars.length-2){if(pos){let charge=nav*cost;ledger.push({date:bars[t+1].date,signalDate:'TERMINAL_EXIT',side:'SELL',price:bars[t+1].close,notional:nav,cost:charge,targetWeight:0,researchOnly:true});nav-=charge;pos=0;}bnav*=1-cost;}
   let ret=nav/before-1,bret=bnav/bbefore-1;returns.push(ret);benchmarkReturns.push(bret);peak=Math.max(peak,nav);
   equity.push({date:bars[t+1].date,nav:nav/100000,equity:nav,benchmark:bnav/100000,drawdown:nav/peak-1,position:pos,score,return:ret});
 }
 return {equity,ledger,metrics:{...metrics(returns),tradeCount:ledger.length,totalCost:ledger.reduce((s,r)=>s+r.cost,0),turnover:turnover/100000},benchmark:metrics(benchmarkReturns),costPerSide:cost,execution:'t-1收盘信号，t日收盘参考成交，t至t+1收盘计收益；可分割研究单位，非真实订单'};
}
function analyze(prices,news=[],options={}){
 const bars=[...prices].sort((a,b)=>a.date.localeCompare(b.date));
 if(bars.length<65)throw Error('至少需要65个有效日线观察值；建议一年以上');
 if(new Set(bars.map(b=>b.symbol)).size!==1)throw Error('请按单个ETF筛选后分析；本工具不混合不同标的时间序列');
 if(new Set(bars.map(b=>b.date)).size!==bars.length)throw Error('分析数据存在重复日期');
 for(let b of bars)if(!['open','high','low','close','volume'].every(k=>finite(b[k])&&b[k]>0)||b.high<Math.max(b.open,b.close,b.low)||b.low>Math.min(b.open,b.close,b.high))throw Error('分析数据OHLCV无效');
 const fee=options.feeBps===undefined?3:Number(options.feeBps),slip=options.slippageBps===undefined?5:Number(options.slippageBps);
 if(!finite(fee)||!finite(slip)||fee<0||slip<0||fee+slip>=1000)throw Error('成本必须是有限非负数，合计低于1000 bps');
 let index=Math.max(42,Math.floor(bars.length*.6)),daily=newsFeatures(bars,news),values=featureValues(bars,daily),directions={};
 let factors=FACTOR_DEFS.map(([key,label])=>{let train=ic(values[key],bars,20,index),test=ic(values[key],bars,index,bars.length);let direction=(train.spearman||0)>=0?1:-1;directions[key]=direction;return {key,label,values:values[key],trainIC:train.spearman,testIC:test.spearman,trainPearson:train.pearson,testPearson:test.pearson,direction,samples:train.samples,testSamples:test.samples};});
 let selectionAudit=[],selected;
 if(!options.factors&&options.factor==='auto'){
   const ranked=factors.filter(f=>finite(f.trainIC)&&f.samples>=30).sort((a,b)=>Math.abs(b.trainIC)-Math.abs(a.trainIC)||a.key.localeCompare(b.key));
   selected=[];const reasons={};
   for(let f of ranked){
     const inverseDuplicate=(f.key==='mom5'&&selected.includes('reversal5'))||(f.key==='reversal5'&&selected.includes('mom5'));
     if(inverseDuplicate)reasons[f.key]='inverse_duplicate';
     else if(selected.length>=3)reasons[f.key]='outside_top3';
     else {selected.push(f.key);reasons[f.key]='selected_by_train_abs_ic';}
   }
   selectionAudit=factors.map(f=>({key:f.key,label:f.label,trainIC:f.trainIC,trainSamples:f.samples,eligible:finite(f.trainIC)&&f.samples>=30,selected:selected.includes(f.key),rank:ranked.findIndex(r=>r.key===f.key)+1||null,reason:reasons[f.key]||(f.samples<30?'insufficient_train_samples':'undefined_train_ic')}));
   if(!selected.length)throw Error('自动挖掘需要至少30个有效训练标签；请增加历史数据，或手动选择因子');
 }else{
   selected=options.factors||[options.factor||'mom20'];if(typeof selected==='string')selected=[selected];
 }
 if(!selected.length||selected.some(k=>!values[k]))throw Error('请选择有效因子');
 let warnings=['单标的时间序列IC，不是股票横截面选股IC；约一年数据统计能力有限。','方向和标准化仅使用训练集；测试段不能反复调参后继续视为独立。','缠论是可审计的简化识别规则；末端结构会变化，不构成买卖建议。','舆情是词典/用户给分，次日才可用；不是LLM金融推理。'];
 if(!news.length)warnings.push('未导入真实舆情；舆情因子不可验证。');
 if(news.length)warnings.push('新闻样本未证实完整覆盖：无新闻观测日的两个舆情因子保持缺失；关注度只在有观测日期检验，不能解读为全市场报道总量。');
 if(bars.some(b=>!b.amount))warnings.push('缺少成交额：Amihud分母使用close×volume近似，成交量单位会影响结果。');
 return {version:VERSION,bars,provenance:prices.provenance||{source:'内存数据，来源未独立核验',synthetic:false},factors,newsDaily:daily,selectedFactor:selected.join('+'),selectedFactors:selected,selectionAudit,split:{index,date:bars[index].date,trainEnd:bars[index-1].date},backtest:backtest(bars,values,selected,directions,index,(fee+slip)/10000),chan:chan(bars),warnings};
}
function makeDemo(days=260,seed=42){
 let state=seed>>>0;const rand=()=>((state=(1664525*state+1013904223)>>>0)/4294967296),normal=()=>Math.sqrt(-2*Math.log(Math.max(rand(),1e-12)))*Math.cos(2*Math.PI*rand());
 let d=new Date('2025-11-03T00:00:00Z'),close=5,prices=[],news=[];
 for(let i=0;i<days;i++){while([0,6].includes(d.getUTCDay()))d.setUTCDate(d.getUTCDate()+1);let day=d.toISOString().slice(0,10),open=close*Math.exp(normal()*.003);close=open*Math.exp(.0004+Math.sin(i/18)*.002+normal()*.009);let high=Math.max(open,close)*(1+rand()*.008),low=Math.min(open,close)*(1-rand()*.008),volume=Math.round(1e7*(.5+rand()));prices.push({date:day,symbol:'DEMO_GOLD',open,high,low,close,volume,amount:volume*close});
  if(i%7===0)news.push({published_at:day+' 10:00:00',date:day,title:`合成示例${i}：`+(i%14?'黄金ETF资金流入，避险需求增长':'黄金价格走弱，资金流出'),sentiment:i%14?.5:-.5,source:'明确标注的合成新闻',scoring:'合成标签'});
  d.setUTCDate(d.getUTCDate()+1);
 }
 let provenance={source:'固定种子合成OHLCV与合成新闻；非真实行情',synthetic:true,seed,priceBasis:'合成价格',volumeUnit:'合成份额'};
 attach(prices,provenance);return {prices,news,provenance};
}
const API={VERSION,FACTOR_DEFS,csvRows,parsePrices,parseNews,makeDemo,analyze,chan,metrics,newsFeatures,ranks,corr};
if(typeof module!=='undefined'&&module.exports)module.exports=API;root.AurumEngine=API;
})(typeof globalThis!=='undefined'?globalThis:window);
