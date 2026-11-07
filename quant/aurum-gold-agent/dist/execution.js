(function(root){
'use strict';
const E=root.AurumEngine||(typeof require==='function'?require('./engine.js'):null);
const finite=Number.isFinite, avg=a=>a.reduce((s,x)=>s+x,0)/a.length;
const STRATEGIES=[['cash','现金'],['trend20_60','20/60日趋势'],['trend10_40','10/40日趋势'],['breakout20','20日突破/10日退出']];
function config(o={}){
 const c={capital:100000,feeBps:3,minFee:5,slippageBps:5,allocation:.5,lot:100,tick:.001,mode:'open',limitBps:10,train:120,step:40,...o};
 for(const k of ['capital','feeBps','minFee','slippageBps','allocation','lot','tick','limitBps','train','step'])if(!finite(c[k]))throw Error('参数必须为有限数值：'+k);
 if(c.capital<=0||c.feeBps<0||c.minFee<0||c.slippageBps<0||c.feeBps+c.slippageBps>=1000||c.allocation<0||c.allocation>1||c.tick<=0||c.limitBps<0||c.limitBps>=1000||c.lot<1||!Number.isInteger(c.lot)||!Number.isInteger(c.train)||c.train<80||!Number.isInteger(c.step)||c.step<1||!['open','limit'].includes(c.mode))throw Error('资金、费率、整手、仓位或订单参数不合理');
 return c;
}
function validate(bars){if(!Array.isArray(bars)||bars.length<81)throw Error('执行回放至少需要81条单标的日线');let last='',symbol=bars[0].symbol;for(const b of bars){if(b.symbol!==symbol||b.date<=last||!['open','high','low','close'].every(k=>finite(b[k])&&b[k]>0)||b.high<Math.max(b.open,b.close)||b.low>Math.min(b.open,b.close))throw Error('执行回放行情无效或日期未严格递增');last=b.date;}}
const tickPrice=(price,tick,up)=>Number(((up?Math.ceil(price/tick-1e-9):Math.floor(price/tick+1e-9))*tick).toFixed(8));
const fee=(notional,c)=>notional>0?Math.round((Math.max(c.minFee,notional*c.feeBps/10000)+Number.EPSILON)*100)/100:0;
function target(bars,i,key,held){
 if(key==='cash')return false;if(key==='hold')return true;
 if(key==='breakout20'){if(i<20)return false;return held?bars[i].close>=Math.min(...bars.slice(i-10,i).map(b=>b.low)):bars[i].close>Math.max(...bars.slice(i-20,i).map(b=>b.high));}
 const spans={trend20_60:[20,60],trend10_40:[10,40]}[key];if(!spans)throw Error('未知策略');if(i+1<spans[1])return false;
 const fast=avg(bars.slice(i-spans[0]+1,i+1).map(b=>b.close)),slow=avg(bars.slice(i-spans[1]+1,i+1).map(b=>b.close));return bars[i].close>slow&&fast>slow;
}
function signalSchedule(bars,key,start,end){let held=false,s=[];for(let t=0;t<end;t++){const on=target(bars,t,key,held);held=on;if(t+1>=start&&t+1<end)s.push({index:t+1,on,key,signalDate:bars[t].date});}return s;}
function simulate(bars,schedule,options={}){
 const c=config(options);let cash=c.capital,qty=0,basis=0,realized=0,fees=0,slipCost=0,orders=[],fills=[],equity=[],peak=c.capital,dd=0,closed=[],exitGroup=null;
 const buyQty=(budget,price)=>{let n=Math.floor(Math.min(budget,cash)/(price*(1+c.feeBps/10000))/c.lot)*c.lot;while(n>0&&n*price+fee(n*price,c)>Math.min(budget,cash)+1e-8)n-=c.lot;return n;};
 for(const s of schedule){const b=bars[s.index],prev=bars[s.index-1];if(!b||!prev||s.signalDate!==prev.date)throw Error('信号日期必须早于成交日期');
  let side=s.on&&qty===0?'BUY':!s.on&&qty>0?'SELL':null;
  if(side){let limit=c.mode==='limit'?tickPrice(prev.close*(1+(side==='BUY'?-1:1)*c.limitBps/10000),c.tick,side==='SELL'):null;
   const budget=(cash+qty*prev.close)*c.allocation;
   // The quantity is fixed at submission using the known previous close/limit.
   let requested=side==='BUY'?buyQty(budget,limit||prev.close):qty;
   let order={order_id:'P'+String(orders.length+1).padStart(5,'0'),date:b.date,symbol:b.symbol,signal_date:s.signalDate,strategy:s.key,side,tif:'DAY',order_type:c.mode==='limit'?'LIMIT':'NEXT_OPEN_REFERENCE',limit_price:limit,requested_qty:requested,filled_qty:0,cancelled_qty:0,status:'REJECTED',reason:'不足一手或资金不足',currency:'CNY',simulation:true};
   if(requested>0){let touched=c.mode!=='limit'||(side==='BUY'?b.low<=limit:b.high>=limit),reference=c.mode==='limit'?(side==='BUY'?Math.min(b.open,limit):Math.max(b.open,limit)):b.open;
    let px=tickPrice(reference*(1+(side==='BUY'?1:-1)*c.slippageBps/10000),c.tick,side==='BUY');
    if(limit!==null)px=side==='BUY'?Math.min(px,limit):Math.max(px,limit);
    let executed=touched?(side==='BUY'?Math.min(requested,buyQty(budget,px)):requested):0;
    order.filled_qty=executed;order.cancelled_qty=requested-executed;
    order.status=executed===requested?'FILLED':executed?'PARTIAL_CANCELLED':'CANCELLED';order.reason=touched?(executed===requested?'参考成交（模拟）':executed?'资金约束部分成交，剩余日终撤销（模拟）':'资金约束，日终撤销（模拟）'):'未触及限价，日终撤销（模拟）';
    if(executed){const amount=executed*px,cost=fee(amount,c),slip=executed*Math.max(0,side==='BUY'?px-reference:reference-px);fees+=cost;slipCost+=slip;let pnl=0;
     if(side==='BUY'){cash-=amount+cost;qty+=executed;basis+=amount+cost;exitGroup={cost:amount+cost,pnl:0};}
     else {const used=basis*executed/qty;pnl=amount-cost-used;cash+=amount-cost;basis-=used;qty-=executed;realized+=pnl;if(exitGroup)exitGroup.pnl+=pnl;if(qty===0){basis=0;closed.push(exitGroup?.pnl??pnl);exitGroup=null;}}
     fills.push({trade_id:'SIM'+(fills.length+1),order_id:order.order_id,date:b.date,symbol:b.symbol,side,quantity:executed,reference_price:reference,price:px,amount,fee:cost,slippage_cost:slip,cash_flow:side==='BUY'?-amount-cost:amount-cost,cash_after:cash,position_after:qty,realized_pnl:pnl,currency:'CNY',simulation:true});
    }
   }
   orders.push(order);
  }
  const value=qty*b.close,net=cash+value;peak=Math.max(peak,net);dd=Math.min(dd,net/peak-1);equity.push({date:b.date,cash,quantity:qty,mark_price:b.close,market_value:value,equity:net,net_pnl:net-c.capital,realized_pnl:realized,unrealized_pnl:value-basis,drawdown:net/peak-1,strategy:s.key});
 }
 const last=equity.at(-1)||{equity:c.capital,net_pnl:0,unrealized_pnl:0,market_value:0,quantity:0,cash:c.capital};
 return {config:c,orders,fills,equity,metrics:{initialCapital:c.capital,endingEquity:last.equity,netPnl:last.net_pnl,totalReturn:last.equity/c.capital-1,realizedPnl:realized,unrealizedPnl:last.unrealized_pnl,fees,slippageCost:slipCost,estimatedExitFee:fee(last.market_value,c),liquidationEstimate:last.equity-fee(last.market_value,c),maxDrawdown:dd,fillCount:fills.length,cancelledOrders:orders.filter(o=>o.cancelled_qty>0).length,openOrders:0,position:last.quantity,cash:last.cash,closedTrades:closed.length,closedWinRate:closed.length?closed.filter(x=>x>0).length/closed.length:null},assumptions:['历史行情执行回放；没有券商订单或实际成交。','上一日收盘信号，下一交易日开盘参考；限价模式仅假定OHLC触价可成交，未模拟盘口和排队。','买入100份整手、价格0.001元为默认；单笔最低佣金5元为可修改假设，不是你的券商报价。','滑点已计入成交价，盈亏不重复扣减滑点金额；期末持仓按收盘估值，不强行假设平仓。','未处理停牌、涨跌停不可成交、集合竞价、交易容量、分红及出入金；前复权价格不能直接核算实际资金。']};
}
function research(bars,options={}){
 validate(bars);const c=config(options);if(bars.length<=c.train)throw Error('回放需要超过'+c.train+'条日线');let schedule=[],folds=[];
 for(let start=c.train;start<bars.length;start+=c.step){const begin=start-c.train,prefix=bars.slice(begin,start),ranks=STRATEGIES.map(([key,label])=>{const r=simulate(prefix,signalSchedule(prefix,key,60,prefix.length),c);return {key,label,trainNetPnl:r.metrics.netPnl,trainReturn:r.metrics.totalReturn,trainDrawdown:r.metrics.maxDrawdown,score:r.metrics.totalReturn-.5*Math.abs(r.metrics.maxDrawdown)};}).sort((a,b)=>b.score-a.score||a.key.localeCompare(b.key));
  const pick=ranks[0].key,end=Math.min(start+c.step,bars.length);let held=schedule.at(-1)?.on||false;
  for(let t=start;t<end;t++){const on=target(bars,t-1,pick,held);held=on;schedule.push({index:t,on,key:pick,signalDate:bars[t-1].date});}
  folds.push({trainStart:bars[begin].date,trainEnd:bars[start-1].date,testStart:bars[start].date,testEnd:bars[end-1].date,selected:pick,candidates:ranks});
 }
 const walk=simulate(bars,schedule,c),bench=simulate(bars,signalSchedule(bars,'hold',c.train,bars.length),c),cash=simulate(bars,signalSchedule(bars,'cash',c.train,bars.length),c);
 const lastPick=folds.at(-1).selected;return {version:'0.3.0',kind:'HISTORICAL_EXECUTION_REPLAY',currency:'CNY',folds,schedule,walk,benchmark:bench,cash,excessPnl:walk.metrics.netPnl-bench.metrics.netPnl,lastSelected:lastPick,method:'固定候选：现金、20/60趋势、10/40趋势、20突破/10退出；每120日训练、随后40日回放。训练评分=扣费收益−0.5×回撤绝对值；跨段现金和持仓连续。历史已被查看，本次不是未触碰的新样本验证。'};
}
function reduceOrder(order,event){
 const o={...order};if(!Number.isInteger(o.quantity)||o.quantity<=0||!Number.isInteger(o.filled||0)||(o.filled||0)<0||(o.filled||0)>o.quantity)throw Error('订单数量无效');o.filled=o.filled||0;
 if(['FILLED','CANCELLED','REJECTED'].includes(o.status))throw Error('终态订单不能继续改变');
 if(event.type==='CANCEL_REQUEST'){o.status='CANCEL_REQUESTED';}
 else if(event.type==='FILL'){if(!Number.isInteger(event.cumulativeFilled)||event.cumulativeFilled<=o.filled||event.cumulativeFilled>o.quantity)throw Error('累计成交回报无效');o.filled=event.cumulativeFilled;o.status=o.filled===o.quantity?'FILLED':o.status==='CANCEL_REQUESTED'?'CANCEL_REQUESTED':'PARTIAL';}
 else if(event.type==='CANCEL_ACK'){o.status='CANCELLED';}
 else if(event.type==='CANCEL_REJECT'){if(o.status!=='CANCEL_REQUESTED')throw Error('没有撤单请求');o.status=o.filled?'PARTIAL':'OPEN';}
 else if(event.type==='REJECT'){if(o.filled)throw Error('已成交订单不可整单拒绝');o.status='REJECTED';}
 else throw Error('未知回报');return o;
}
function reconcile(text,options={}){
 const capital=options.capital??100000,mark=options.mark;if(!finite(capital)||capital<=0||!finite(mark)||mark<=0)throw Error('初始资金和估值单价必须为正数');let cash=capital,qty=0,basis=0,realized=0,totalFees=0,seen=new Set(),symbol=null,last='';const rows=[];
 for(const r of E.csvRows(text)){
  if(!r.trade_id||seen.has(r.trade_id))throw Error('成交编号缺失或重复');seen.add(r.trade_id);
  if(!/^\d{4}-\d{2}-\d{2}(?:[ T]\d{2}:\d{2}(?::\d{2})?)?$/.test(r.date)||!finite(Date.parse(r.date.slice(0,10)))||new Date(r.date.slice(0,10)+'T00:00:00Z').toISOString().slice(0,10)!==r.date.slice(0,10)||r.date<last)throw Error('成交日期无效或未按时间排序');last=r.date;
  if(!r.symbol||symbol&&r.symbol!==symbol)throw Error('请仅导入一个证券的成交记录');symbol=r.symbol;
  if(options.markDate&&r.date.slice(0,10)>options.markDate)throw Error('成交日期晚于估值日期');
  if(options.symbol&&r.symbol!==options.symbol)throw Error('成交证券与估值行情不匹配');if(r.currency!=='CNY')throw Error('只核算人民币成交；外币须另建账本');
  const n=Number(r.quantity),px=Number(r.price),cost=Number(r.fee),side=(r.side||'').toUpperCase();if(!Number.isInteger(n)||n<=0||!finite(px)||px<=0||r.fee===undefined||r.fee===''||!finite(cost)||cost<0||!['BUY','SELL'].includes(side))throw Error('数量、单价、费用或方向无效');let pnl=0;
  if(side==='BUY'){if(cash+1e-8<n*px+cost)throw Error('买入超出初始资金；请核对出入金和初始持仓');cash-=n*px+cost;qty+=n;basis+=n*px+cost;}
  else {if(n>qty)throw Error('卖出超出持仓；请补齐买入记录或初始持仓');const used=basis*n/qty;cash+=n*px-cost;basis-=used;qty-=n;realized+=pnl=n*px-cost-used;}
  totalFees+=cost;rows.push({...r,side,quantity:n,price:px,amount:n*px,fee:cost,realized_pnl:pnl,cash_after:cash,position_after:qty});
 }
 const marketValue=qty*mark,unrealized=marketValue-basis,equity=cash+marketValue;return {kind:'USER_DECLARED_FILLS_NOT_BROKER_VERIFIED',currency:'CNY',symbol,capital,mark,cash,quantity:qty,marketValue,equity,netPnl:equity-capital,realizedPnl:realized,unrealizedPnl:unrealized,totalFees,rows,note:'按用户声明的已成交记录计算；未连接券商核验。不含未导入成交、出入金、分红、税费补扣或初始持仓。未成交委托不属于成交记录。'};
}
const API={config,target,signalSchedule,simulate,research,reduceOrder,reconcile,STRATEGIES};root.AurumExecution=API;if(typeof module!=='undefined'&&module.exports)module.exports=API;
})(typeof globalThis!=='undefined'?globalThis:window);
