"""Local-only expense and incoming-credit regression, with a persistent review ledger."""
from pathlib import Path
from contextlib import contextmanager
from datetime import date,datetime,timedelta,timezone
from decimal import Decimal,InvalidOperation
import sqlite3,json,hashlib,base64,io,csv,zipfile,uuid
import numpy as np
import pandas as pd
import joblib
from sklearn.base import clone
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.linear_model import Ridge
from sklearn.dummy import DummyRegressor
from sklearn.ensemble import ExtraTreesRegressor,GradientBoostingRegressor
from sklearn.model_selection import TimeSeriesSplit
from sklearn.metrics import mean_absolute_error,mean_squared_error,r2_score

ROOT=Path(__file__).resolve().parent
DATA=ROOT/'data';MODELS=ROOT/'models';RESULTS=ROOT/'results'
DEFAULT=['food','grocery','entertainment','transport','bills','education','healthcare','fashion','online_shopping','offline_shopping','miscellaneous','income','excluded_transfer','unknown']
FIELDS=['Date','Time','Transaction Details','Transaction ID','UTR','Transaction Type','Amount']
def today():return datetime.now(timezone(timedelta(hours=5,minutes=30))).date()
def valid_date(v):
    try:d=date.fromisoformat(v)
    except (ValueError,TypeError):raise ValueError('Use a valid YYYY-MM-DD date.')
    if d>today():raise ValueError('Actual payments cannot be dated in the future.')
    return d
def paise(v):
    try:n=Decimal(str(v).replace(',','').strip())
    except InvalidOperation:raise ValueError('Invalid amount.')
    if not n.is_finite() or n<=0 or n>100000000 or n*100!=(n*100).to_integral_value():raise ValueError('Amount must be positive, with at most two decimal places.')
    return int(n*100)
@contextmanager
def db():
    DATA.mkdir(exist_ok=True)
    conn=sqlite3.connect(DATA/'tracker.sqlite3',timeout=30);conn.row_factory=sqlite3.Row
    conn.executescript('''CREATE TABLE IF NOT EXISTS tx(id TEXT PRIMARY KEY,date TEXT,description TEXT,direction TEXT,amount INTEGER,category TEXT,source TEXT,deleted INTEGER DEFAULT 0);
    CREATE TABLE IF NOT EXISTS purged(id TEXT PRIMARY KEY);
    CREATE TABLE IF NOT EXISTS complete(date TEXT PRIMARY KEY);
    CREATE TABLE IF NOT EXISTS categories(name TEXT PRIMARY KEY);
    CREATE TABLE IF NOT EXISTS forecasts(id INTEGER PRIMARY KEY,created TEXT,date TEXT,expense REAL,credit REAL,history_end TEXT);''')
    conn.executemany('INSERT OR IGNORE INTO categories VALUES (?)',[(c,) for c in DEFAULT]);conn.commit()
    try:
        with conn:yield conn
    finally:conn.close()
def rows(deleted=0):
    with db() as c:return [dict(r) for r in c.execute('SELECT * FROM tx WHERE deleted=? ORDER BY date,id',(deleted,))]
def categories():
    with db() as c:return [r[0] for r in c.execute('SELECT name FROM categories ORDER BY name')]
def completed():
    with db() as c:return {r[0] for r in c.execute('SELECT date FROM complete')}
def fingerprint():
    return hashlib.sha256(json.dumps([rows(),sorted(completed())],sort_keys=True).encode()).hexdigest()
def history_end():
    r=rows()
    if not r:return None
    day=date.fromisoformat(r[0]['date']);done=completed();end=day-timedelta(days=1)
    while str(day) in done:end=day;day+=timedelta(days=1)
    return end
def metadata():
    p=RESULTS/'metrics.json'
    return json.loads(p.read_text()) if p.exists() else None
def state():
    r=rows();m=metadata();end=history_end()
    with db() as c:logs=[dict(x) for x in c.execute('SELECT * FROM forecasts ORDER BY id DESC LIMIT 20')]
    return dict(transactions=r,deleted=rows(1),categories=categories(),completed=sorted(completed()),today=str(today()),history_end=str(end) if end else None,unreviewed=sum(x['category']=='unknown' for x in r),model=m,stale=not m or m['fingerprint']!=fingerprint(),history=logs)
def import_file(p):
    suffix=Path(str(p.get('filename',''))).suffix.lower()
    if suffix not in ['.csv','.xlsx']:raise ValueError('Choose CSV or .xlsx; save older .xls files as .xlsx first.')
    try:content=base64.b64decode(p['content'],validate=True)
    except Exception:raise ValueError('Invalid file content.')
    if not 0<len(content)<=5*1024*1024:raise ValueError('Maximum file size is 5 MB.')
    tables=[]
    if suffix=='.xlsx':
        try:
            with zipfile.ZipFile(io.BytesIO(content)) as z:
                if sum(x.file_size for x in z.infolist())>30*1024*1024:raise ValueError('Workbook too large when expanded.')
            from openpyxl import load_workbook
            book=load_workbook(io.BytesIO(content),read_only=True,data_only=False)
            try:
                for sheet in book:
                    table=[]
                    for n,row in enumerate(sheet.iter_rows(values_only=True)):
                        if n>50000:raise ValueError('Too many worksheet rows.')
                        table.append(list(row))
                    tables.append(table)
            finally:book.close()
        except Exception as e:raise ValueError('Could not read Excel file: '+str(e))
    else:
        try:tables=[list(csv.reader(io.StringIO(content.decode('utf-8-sig'))))]
        except Exception:raise ValueError('CSV must be UTF-8.')
    found=[]
    for table in tables:
        for i,row in enumerate(table):
            headers=[str(v).strip() for v in row]
            if set(FIELDS)-{'UTR'}<=set(headers):found.append((headers,table[i+1:]));break
    if len(found)!=1:raise ValueError('Use one transaction table with Date, Time, Transaction Details, Transaction ID, Transaction Type, Amount; UTR optional.')
    headers,table=found[0];new={};duplicates=0
    for raw in table:
        r=dict(zip(headers,raw));kind=str(r.get('Transaction Type') or '').strip().upper();identity=str(r.get('Transaction ID') or '').strip()
        if not kind and not identity:continue
        if kind not in ['DEBIT','CREDIT'] or not identity:raise ValueError('Each transaction needs DEBIT/CREDIT and a transaction ID.')
        d=r['Date']
        if isinstance(d,datetime):d=d.date()
        elif not isinstance(d,date):
            value=str(d).replace('Sept ','Sep ').strip()
            try:d=datetime.strptime(value,'%b %d, %Y').date()
            except ValueError:
                try:d=date.fromisoformat(value)
                except ValueError:raise ValueError('Date must use PhonePe format (Oct 25, 2026), ISO YYYY-MM-DD, or an Excel date cell.')
        valid_date(str(d));description=' '.join(str(r['Transaction Details'] or '').split())
        if not description or len(description)>300:raise ValueError('Payment description must contain 1–300 characters.')
        key=hashlib.sha256(identity.encode()).hexdigest();entry=dict(id=key,date=str(d),description=description,direction=kind,amount=paise(r['Amount']),category='unknown',source='statement',deleted=0)
        if key in new:
            if new[key]!=entry:raise ValueError('Conflicting transaction IDs within file.')
            duplicates+=1
        new[key]=entry
    if not new:raise ValueError('No transactions found.')
    with db() as c:
        existing={r['id']:dict(r) for r in c.execute('SELECT * FROM tx')};purged={r[0] for r in c.execute('SELECT id FROM purged')};add=[]
        for key,r in new.items():
            if key in purged:duplicates+=1;continue
            if key in existing:
                if any(existing[key][f]!=r[f] for f in ['date','description','direction','amount']):raise ValueError('Existing ID has different transaction details. Nothing imported.')
                duplicates+=1;continue
            if any(x['source']=='manual' and not x['deleted'] and all(x[f]==r[f] for f in ['date','direction','amount']) for x in existing.values()):raise ValueError('Possible manual-payment duplicate on '+r['date']+'. Review/delete the manual entry first.')
            add.append(r)
        for r in add:
            c.execute('INSERT INTO tx VALUES (:id,:date,:description,:direction,:amount,:category,:source,:deleted)',r);c.execute('DELETE FROM complete WHERE date=?',(r['date'],))
    return dict(imported=len(add),duplicates_skipped=duplicates,message='Review both incoming and outgoing transactions. Confirm your statement coverage, including zero-transaction days.')
def mutate(action,p):
    if action=='upload':return import_file(p)
    if action=='category':
        name=str(p.get('name','')).strip().lower().replace(' ','_')
        if not name or len(name)>40 or not all(x.isalnum() or x=='_' for x in name):raise ValueError('Category: 1–40 letters, digits or spaces.')
        with db() as c:c.execute('INSERT OR IGNORE INTO categories VALUES (?)',(name,))
    elif action=='entry':
        d=str(valid_date(p.get('date')));desc=str(p.get('description','')).strip();kind=p.get('direction');cat=p.get('category')
        if not desc or len(desc)>300 or kind not in ['DEBIT','CREDIT'] or cat not in categories() or cat=='unknown':raise ValueError('Enter a description, payment type and category.')
        key=p.get('id')
        try:uuid.UUID(key)
        except Exception:raise ValueError('Invalid save identifier.')
        record=(key,d,desc,kind,paise(p.get('amount')),cat,'manual',0)
        with db() as c:
            old=c.execute('SELECT * FROM tx WHERE id=?',(key,)).fetchone()
            if old:
                if tuple(old)!=record:raise ValueError('Save ID already used.')
            else:c.execute('INSERT INTO tx VALUES (?,?,?,?,?,?,?,?)',record);c.execute('DELETE FROM complete WHERE date=?',(d,))
    elif action=='review':
        cat=p.get('category')
        if cat not in categories():raise ValueError('Invalid category.')
        with db() as c:
            r=c.execute('SELECT * FROM tx WHERE id=? AND deleted=0',(p.get('id'),)).fetchone()
            if not r:raise ValueError('Transaction not found.')
            if p.get('same_merchant') is True:c.execute('UPDATE tx SET category=? WHERE description=? AND direction=? AND deleted=0',(cat,r['description'],r['direction']))
            else:c.execute('UPDATE tx SET category=? WHERE id=?',(cat,r['id']))
    elif action=='complete':
        start=valid_date(p.get('start'));end=valid_date(p.get('end'));r=rows()
        if not r or start<date.fromisoformat(r[0]['date']) or start>end or (end-start).days>3660:raise ValueError('Invalid completion range.')
        with db() as c:
            c.executemany('INSERT OR IGNORE INTO complete VALUES (?)',[(str(start+timedelta(days=i)),) for i in range((end-start).days+1)])
    elif action in ['delete','restore','purge']:
        with db() as c:
            r=c.execute('SELECT * FROM tx WHERE id=?',(p.get('id'),)).fetchone()
            if not r:raise ValueError('Transaction not found.')
            if action=='purge':
                if not r['deleted'] or p.get('confirmation')!='DELETE':raise ValueError('Move to trash and type DELETE first.')
                c.execute('INSERT OR IGNORE INTO purged VALUES (?)',(r['id'],));c.execute('DELETE FROM tx WHERE id=?',(r['id'],))
            else:c.execute('UPDATE tx SET deleted=? WHERE id=?',(int(action=='delete'),r['id']))
            c.execute('DELETE FROM complete WHERE date=?',(r['date'],))
    else:raise ValueError('Unknown action.')
    return {'saved':True}
def daily_history():
    r=rows();end=history_end()
    if not r or end<date.fromisoformat(r[0]['date']):raise ValueError('Upload payments and confirm complete days first.')
    if any(x['category']=='unknown' for x in r):raise ValueError('Review all transactions first, including credits. Exclude transfers/refunds that should not fund spending.')
    index=pd.date_range(r[0]['date'],end);daily=pd.DataFrame(0.,index=index,columns=['expense','credit'])
    for x in r:
        d=pd.Timestamp(x['date'])
        if d in index and x['category']!='excluded_transfer':daily.loc[d,'expense' if x['direction']=='DEBIT' else 'credit']+=x['amount']/100
    return daily
def features(d):
    f=pd.DataFrame(index=d.index)
    for target in d.columns:
        prior=d[target].shift(1)
        for lag in [1,7]:f[f'{target}_lag{lag}']=d[target].shift(lag)
        for window in [7,28]:f[f'{target}_mean{window}']=prior.rolling(window).mean()
    f['weekday_sin']=np.sin(2*np.pi*f.index.weekday/7);f['weekday_cos']=np.cos(2*np.pi*f.index.weekday/7)
    f['monthday']=f.index.day
    return f
def scores(y,p):
    return dict(MAE=float(mean_absolute_error(y,p)),RMSE=float(mean_squared_error(y,p)**.5),R2=float(r2_score(y,p)) if len(y)>1 and np.var(y)>0 else None)
def train():
    d=daily_history();x=features(d).dropna();y=d.loc[x.index]
    if len(x)<42:raise ValueError('Need at least 70 consecutive complete days (28 history days + 42 modelling days). The sample covers 90 days.')
    cut=int(len(x)*.8);results={};models={};comparison=[]
    choices={'Historical mean':DummyRegressor(),'Ridge':make_pipeline(StandardScaler(),Ridge(alpha=10)),'Extra trees':ExtraTreesRegressor(n_estimators=100,min_samples_leaf=5,max_depth=5,random_state=42,n_jobs=1),'Gradient boosting':GradientBoostingRegressor(n_estimators=60,max_depth=2,min_samples_leaf=5,random_state=42)}
    for target in ['expense','credit']:
        if target=='credit' and (d.credit>0).sum()<6:raise ValueError('Need at least six included credit dates to train incoming-money regression. Do not invent credits.')
        cv=[]
        for name,model in choices.items():
            errors=[]
            for tr,va in TimeSeriesSplit(n_splits=3).split(x.iloc[:cut]):
                fitted=clone(model).fit(x.iloc[tr],y[target].iloc[tr]);pred=np.maximum(0,fitted.predict(x.iloc[va]));errors.append(mean_squared_error(y[target].iloc[va],pred)**.5)
            cv.append((float(np.mean(errors)),name))
        best=min(cv)[1]
        for error,name in cv:
            fitted=clone(choices[name]).fit(x.iloc[:cut],y[target].iloc[:cut]);test=scores(y[target].iloc[cut:],np.maximum(0,fitted.predict(x.iloc[cut:])))
            comparison.append(dict(target=target,model=name,cv_RMSE=error,**test))
            if name==best:results[target]=dict(selected_model=name,test=test,train_days=cut,test_days=len(x)-cut)
        models[target]=clone(choices[best]).fit(x,y[target])
    result=dict(**results,fingerprint=fingerprint(),history_end=str(d.index.max().date()),comparison=comparison,note='Expanding time-based validation selects each model; final 20% reports one-day holdout error. Deployment refits on all complete history. Multi-day forecasts are recursive and are not validated by these one-day scores.')
    MODELS.mkdir(exist_ok=True);RESULTS.mkdir(exist_ok=True)
    joblib.dump(models,MODELS/'regressors.tmp');(MODELS/'regressors.tmp').replace(MODELS/'regressors.joblib')
    (RESULTS/'metrics.tmp').write_text(json.dumps(result,indent=2));(RESULTS/'metrics.tmp').replace(RESULTS/'metrics.json')
    pd.DataFrame(comparison).to_csv(RESULTS/'model_comparison.csv',index=False)
    return result
def allocate(total,weights):
    cents=round(total*100);values=np.array(list(weights.values()));raw=cents*values;parts=np.floor(raw).astype(int)
    for i in np.argsort(-(raw-parts),kind='stable')[:cents-int(parts.sum())]:parts[i]+=1
    return [dict(category=k,amount_inr=int(v)/100) for k,v in zip(weights,parts)]
def forecast(target):
    meta=metadata()
    if not meta or meta['fingerprint']!=fingerprint():raise ValueError('Retrain after changing transactions, reviews or completed days.')
    d=daily_history();end=d.index.max();target=pd.Timestamp(date.fromisoformat(target))
    if not 1<=(target-end).days<=14:raise ValueError('Choose one to fourteen days beyond confirmed history.')
    models=joblib.load(MODELS/'regressors.joblib');cats={c:0 for c in categories() if c not in ['unknown','excluded_transfer','income']}
    for r in rows():
        if r['direction']=='DEBIT' and r['category']!='excluded_transfer' and str((end-pd.Timedelta(days=27)).date())<=r['date']<=str(end.date()):cats[r['category']]=cats.get(r['category'],0)+r['amount']
    total=sum(cats.values());weights={k:v/total for k,v in cats.items()} if total else {'unallocated':1.}
    days=[]
    for day in pd.date_range(end+pd.Timedelta(days=1),target):
        d.loc[day]=[0.,0.];f=features(d).loc[[day]];est={k:round(max(0,float(model.predict(f)[0])),2) for k,model in models.items()};d.loc[day]=[est['expense'],est['credit']]
        days.append(dict(date=str(day.date()),expense_inr=est['expense'],credit_inr=est['credit'],categories=allocate(est['expense'],weights)))
    # The seven-day cash-flow window ends on the selected date, combining actual completed dates and forecasts.
    start=target-pd.Timedelta(days=6);window=d.loc[start:target];credits=float(window.credit.sum());expenses=float(window.expense.sum())
    result=dict(horizon=(target-end).days,extended_forecast=(target-end).days>7,date=str(target.date()),history_end=str(end.date()),days=days,expense_inr=days[-1]['expense_inr'],credit_inr=days[-1]['credit_inr'],category_breakdown=days[-1]['categories'],period_total_inr=round(sum(x['expense_inr'] for x in days),2),cashflow=dict(start=str(start.date()),end=str(target.date()),credits=round(credits,2),expenses=round(expenses,2),difference=round(credits-expenses,2),status='Expected shortfall' if expenses>credits else 'Within estimated receipts'),note='Category amounts allocate the expense forecast using the last 28 completed days of spending; they are not independent category forecasts. Credits are receipts, not disposable income or a bank balance. Loans, refunds and own-account transfers should be excluded where appropriate. Missing days use predictions, never fabricated actuals.')
    with db() as c:
        for x in days:c.execute('INSERT INTO forecasts(created,date,expense,credit,history_end) VALUES (?,?,?,?,?)',(datetime.now(timezone.utc).isoformat(),x['date'],x['expense_inr'],x['credit_inr'],str(end.date())))
    return result
