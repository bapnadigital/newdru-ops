"""Pydantic models for Newdru retail operations."""
from pydantic import BaseModel, Field, EmailStr, field_validator
from typing import List, Optional, Literal, Dict, Any
from datetime import datetime, timezone
import uuid


def _blank_to_none(v):
    """Coerce empty strings (and whitespace-only strings) to None so
    Optional[EmailStr] / Optional[str] fields don't 422 when the frontend
    sends '' instead of omitting the key."""
    if isinstance(v, str) and v.strip() == "":
        return None
    return v


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def gen_id() -> str:
    return str(uuid.uuid4())


ROLE_OWNER = "owner"
ROLE_STORE_MANAGER = "store_manager"
ROLE_CASHIER = "cashier"
ROLE_WH_MANAGER = "warehouse_manager"
ROLE_WH_STAFF = "warehouse_staff"

ALL_ROLES = [ROLE_OWNER, ROLE_STORE_MANAGER, ROLE_CASHIER, ROLE_WH_MANAGER, ROLE_WH_STAFF]
# Cost / buy price / margin are OWNER-ONLY across the whole app.
COST_HIDDEN_ROLES = [ROLE_STORE_MANAGER, ROLE_CASHIER, ROLE_WH_MANAGER, ROLE_WH_STAFF]

# Role buckets for permission checks
STORE_ROLES = [ROLE_STORE_MANAGER, ROLE_CASHIER]
WAREHOUSE_ROLES = [ROLE_WH_MANAGER, ROLE_WH_STAFF]

LOC_STORE = "STORE"
LOC_BHIWANDI = "BHIWANDI"
LOC_AMAZON_FC = "AMAZON_FC"
LOC_FLIPKART_FC = "FLIPKART_FC"

LOCATIONS = [
    {"code": LOC_STORE, "name": "Newdru Store", "type": "store", "editable": True},
    {"code": LOC_BHIWANDI, "name": "Bhiwandi Warehouse", "type": "warehouse", "editable": True},
    {"code": LOC_AMAZON_FC, "name": "Amazon FC", "type": "external", "editable": False},
    {"code": LOC_FLIPKART_FC, "name": "Flipkart FC", "type": "external", "editable": False},
]


class UserBase(BaseModel):
    email: EmailStr
    name: str
    role: str = ROLE_CASHIER
    active: bool = True


class UserCreate(UserBase):
    # Staff passwords: at least 10 characters.
    password: str = Field(min_length=10, max_length=128)


class UserUpdate(BaseModel):
    name: Optional[str] = None
    role: Optional[str] = None
    active: Optional[bool] = None
    password: Optional[str] = Field(default=None, min_length=10, max_length=128)


class LoginIn(BaseModel):
    email: EmailStr
    password: str = Field(max_length=128)


class ProductDimensions(BaseModel):
    length_cm: Optional[float] = None
    width_cm: Optional[float] = None
    height_cm: Optional[float] = None


class ProductBase(BaseModel):
    sku: str
    name: str
    brand: Optional[str] = None
    category: Optional[str] = None
    variant: Optional[str] = None
    mrp: float = 0.0
    gst_rate: float = 18.0
    hsn: Optional[str] = None
    images: List[str] = Field(default_factory=list)
    channel_scope: Literal["online_offline", "offline_only"] = "offline_only"
    status: Literal["active", "inactive"] = "active"
    barcode: Optional[str] = None
    barcode_type: Literal["FNSKU", "CODE128"] = "CODE128"
    buy_price: float = 0.0
    sell_price: float = 0.0
    cogs_per_unit: Optional[float] = None    # GST-inclusive landed cost / price floor
    unit_weight_g: Optional[float] = None
    dimensions: Optional[ProductDimensions] = None
    units_per_carton: int = 1
    carton_weight_g: Optional[float] = None
    carton_dimensions: Optional[ProductDimensions] = None
    warranty_months: int = 6   # Newdru default: 6-month manufacturing-defect warranty


class ProductCreate(ProductBase):
    pass


class ProductUpdate(BaseModel):
    name: Optional[str] = None
    brand: Optional[str] = None
    category: Optional[str] = None
    variant: Optional[str] = None
    mrp: Optional[float] = None
    gst_rate: Optional[float] = None
    hsn: Optional[str] = None
    images: Optional[List[str]] = None
    channel_scope: Optional[str] = None
    status: Optional[str] = None
    barcode: Optional[str] = None
    barcode_type: Optional[str] = None
    buy_price: Optional[float] = None
    sell_price: Optional[float] = None
    cogs_per_unit: Optional[float] = None
    unit_weight_g: Optional[float] = None
    dimensions: Optional[ProductDimensions] = None
    units_per_carton: Optional[int] = None
    carton_weight_g: Optional[float] = None
    carton_dimensions: Optional[ProductDimensions] = None
    warranty_months: Optional[int] = None


class InventoryAdjust(BaseModel):
    product_id: str
    location_code: str
    quantity_delta: int
    reason: str


class LowStockThresholdSet(BaseModel):
    product_id: str
    location_code: str
    low_stock_threshold: int


class TransferItem(BaseModel):
    product_id: str
    sku: str
    name: str
    requested_qty: int
    dispatched_qty: int = 0
    received_qty: int = 0


class TransferCreate(BaseModel):
    from_location: str
    to_location: str
    items: List[TransferItem]
    notes: Optional[str] = None


class CustomerBase(BaseModel):
    name: str
    phone: Optional[str] = None
    email: Optional[EmailStr] = None
    channel: str = "store"
    tags: List[str] = Field(default_factory=list)

    _norm_blanks = field_validator("phone", "email", mode="before")(
        lambda cls, v: _blank_to_none(v)
    )


class CustomerCreate(CustomerBase):
    pass


class CustomerUpdate(BaseModel):
    name: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[EmailStr] = None
    channel: Optional[str] = None
    tags: Optional[List[str]] = None

    _norm_blanks = field_validator("name", "phone", "email", "channel", mode="before")(
        lambda cls, v: _blank_to_none(v)
    )


class SaleLine(BaseModel):
    product_id: str
    sku: str
    name: str
    hsn: Optional[str] = None
    gst_rate: float = 18.0
    quantity: int
    unit_price: float
    discount: float = 0.0
    line_subtotal: Optional[float] = None
    tax_amount: Optional[float] = None
    line_total: Optional[float] = None


class PaymentPart(BaseModel):
    method: Literal["cash", "card", "upi"] = "cash"
    amount: float


class SaleCreate(BaseModel):
    items: List[SaleLine]
    customer_id: Optional[str] = None
    customer: Optional[CustomerCreate] = None
    cart_discount: float = 0.0
    payments: List[PaymentPart]
    notes: Optional[str] = None
    client_ref: Optional[str] = None
    # Phase-3 attribution hooks (optional in Phase 1):
    campaign_tag: Optional[str] = None   # free-text "How did you hear?" / campaign source
    discount_code: Optional[str] = None  # coupon / promo code applied at POS
    # Below-COGS admin override — supplied when any line is priced below COGS
    admin_override_email: Optional[str] = None
    admin_override_password: Optional[str] = None
    admin_override_reason: Optional[str] = None
