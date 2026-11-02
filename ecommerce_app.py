"""EduCommerce: in-memory application for practicing checkout and automated testing."""
from dataclasses import dataclass, field
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional

D=lambda x: Decimal(str(x))

def money(x): return D(x).quantize(D('1'), rounding=ROUND_HALF_UP)

@dataclass
class Product:
    sku:str; title:str; price:Decimal; stock:int; active:bool=True
@dataclass
class Customer:
    customer_id:str; authenticated:bool=True; used_codes:set=field(default_factory=set)
@dataclass
class CartLine:
    sku:str; quantity:int
@dataclass
class Voucher:
    code:str; percent:int; min_subtotal:Decimal; cap:Decimal; active:bool=True
@dataclass
class Order:
    order_id:str; customer_id:str; total:Decimal; status:str; lines:list; discount:Decimal; shipping:Decimal; payment_method:str

class Catalog:
    def __init__(self):
        self.products={'A':Product('A','Wireless Mouse',D(200000),20),
                       'B':Product('B','Mechanical Keyboard',D(300000),15),
                       'C':Product('C','USB-C Hub',D(150000),12)}
    def get(self,sku):
        p=self.products.get(sku)
        if not p or not p.active: raise ValueError('PRODUCT_UNAVAILABLE')
        return p

class Cart:
    def __init__(self,catalog): self.catalog=catalog; self.lines=[]
    def add(self,sku,quantity):
        self.catalog.get(sku)
        if not isinstance(quantity,int) or quantity<1: raise ValueError('INVALID_QUANTITY')
        existing=next((x for x in self.lines if x.sku==sku),None)
        if existing: existing.quantity+=quantity
        else: self.lines.append(CartLine(sku,quantity))
    def subtotal(self): return sum((self.catalog.get(x.sku).price*x.quantity for x in self.lines),D(0))

class Inventory:
    def __init__(self,catalog): self.catalog=catalog
    def reserve(self,lines):
        for line in lines:
            if self.catalog.get(line.sku).stock < line.quantity: raise ValueError('OUT_OF_STOCK')
        for line in lines: self.catalog.get(line.sku).stock-=line.quantity
    def release(self,lines):
        for line in lines: self.catalog.get(line.sku).stock+=line.quantity

class Promotions:
    def __init__(self): self.codes={'SAVE10':Voucher('SAVE10',10,D(500000),D(100000))}
    def discount(self, code, subtotal, customer):
        if not code: return D(0)
        v=self.codes.get(code)
        if not v or not v.active: raise ValueError('INVALID_VOUCHER')
        if not customer.authenticated: raise ValueError('LOGIN_REQUIRED')
        if code in customer.used_codes: raise ValueError('VOUCHER_USED')
        # Validate minimum subtotal for voucher eligibility.
        if subtotal <= v.min_subtotal: raise ValueError('MIN_SUBTOTAL_NOT_MET')
        return min(money(subtotal*v.percent/D(100)),v.cap)

class Shipping:
    def calculate(self,subtotal,area):
        if area not in ('inner','outer'): raise ValueError('INVALID_AREA')
        return D(0) if area=='inner' and subtotal>=D(500000) else (D(30000) if area=='inner' else D(50000))

class Payments:
    def __init__(self): self.charges=[]
    def collect(self,amount,method,approved,key):
        if method=='COD': return 'PENDING_COD'
        if method!='ONLINE': raise ValueError('INVALID_PAYMENT_METHOD')
        if not approved: raise ValueError('PAYMENT_DECLINED')
        self.charges.append({'key':key,'amount':amount})
        return 'PAID'

class Checkout:
    def __init__(self,catalog=None):
        self.catalog=catalog or Catalog(); self.inventory=Inventory(self.catalog)
        self.promotions=Promotions(); self.shipping=Shipping(); self.payments=Payments()
        self.orders={}; self.by_key={}; self.counter=0
    def place(self,customer,cart,area='inner',voucher=None,method='COD',approved=True,key='REQ-001'):
        if not customer.authenticated: raise ValueError('LOGIN_REQUIRED')
        if not cart.lines: raise ValueError('EMPTY_CART')
        subtotal=cart.subtotal()
        discount=self.promotions.discount(voucher,subtotal,customer)
        shipping=self.shipping.calculate(subtotal,area)
        total=max(D(0),subtotal-discount+shipping)
        # Reserve stock during the checkout transaction.
        self.inventory.reserve(cart.lines)
        if key in self.by_key: return self.orders[self.by_key[key]]
        # Process the online payment outcome.
        payment_state=self.payments.collect(total,method,approved,key)
        self.counter+=1
        order=Order(f'ORD-{self.counter:04d}',customer.customer_id,total,payment_state,
                    [(x.sku,x.quantity) for x in cart.lines],discount,shipping,method)
        self.orders[order.order_id]=order; self.by_key[key]=order.order_id
        if voucher: customer.used_codes.add(voucher)
        return order

def fixture(subtotal_case='600k'):
    service=Checkout(); customer=Customer('U_NEW'); cart=Cart(service.catalog)
    if subtotal_case=='500k': cart.add('A',1); cart.add('B',1)
    elif subtotal_case=='499999':
        cart.add('A',1); cart.add('B',1); service.catalog.products['B'].price=D(299999)
    elif subtotal_case=='1000k': cart.add('A',5)
    elif subtotal_case=='1500k': cart.add('B',5)
    elif subtotal_case=='600k': cart.add('A',3)
    elif subtotal_case=='300k': cart.add('B',1)
    else: raise ValueError('UNKNOWN_FIXTURE')
    return service,customer,cart
