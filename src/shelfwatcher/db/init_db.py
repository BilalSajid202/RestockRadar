import os
from sqlalchemy import text
from src.shelfwatcher.db.session import engine, Base, SessionLocal
from src.shelfwatcher.db.models import Store, User, Camera, Shelf, SKU, Planogram, Supplier, SKUSupplier, Setting


def init_db(seed: bool = True):
    """Creates all tables and read-only views, and optionally seeds initial data."""
    # Create tables
    Base.metadata.create_all(bind=engine)

    # Create views
    views_path = os.path.join(os.path.dirname(__file__), "views.sql")
    if os.path.exists(views_path):
        with open(views_path, "r", encoding="utf-8") as f:
            sql_script = f.read()
        with engine.connect() as conn:
            for statement in sql_script.split(";"):
                stmt = statement.strip()
                if stmt:
                    conn.execute(text(stmt))
            conn.commit()

    if seed:
        seed_data()


def seed_data():
    """Populates basic sample store, user, SKUs, and shelves."""
    db = SessionLocal()
    try:
        # Check if already seeded
        if db.query(Store).first():
            return

        # 1. Store
        store = Store(name="Islamabad Superstore #1", timezone="Asia/Karachi", default_language="en")
        db.add(store)
        db.flush()

        # 2. Admin & Manager Users
        admin = User(
            store_id=store.store_id,
            email="admin@shelfwatcher.local",
            role="Admin",
            language="en",
            password_hash="$2b$12$e80yvYq5eZt9Z/eK...",  # demo hash
        )
        manager = User(
            store_id=store.store_id,
            email="manager@shelfwatcher.local",
            role="Manager",
            language="en",
            password_hash="$2b$12$e80yvYq5eZt9Z/eK...",
        )
        db.add_all([admin, manager])

        # 3. Camera
        camera = Camera(
            store_id=store.store_id,
            name="Aisle 3 Cam (Beverages & Dairy)",
            source_type="replay",
            status="ACTIVE"
        )
        db.add(camera)
        db.flush()

        # 4. Shelves
        shelf1 = Shelf(
            camera_id=camera.camera_id,
            name="Dairy & Drinks Shelf A3-L1",
            aisle="A3",
            level="L1",
            total_facings=10,
            backroom_units=15,
            depth_factor=1.0,
            roi_polygon=[[50, 100], [900, 100], [900, 450], [50, 450]]
        )
        db.add(shelf1)
        db.flush()

        # 5. Suppliers
        sup_dairy = Supplier(name="Habib Dairy Corp", email="orders@habibdairy.local", phone="+92-300-1112233", lead_time_days=1.0, moq=12)
        sup_grocery = Supplier(name="National Foods Ltd", email="orders@nationalfoods.local", phone="+92-300-4445566", lead_time_days=2.0, moq=24)
        db.add_all([sup_dairy, sup_grocery])
        db.flush()

        # 6. 10 Mini-Shelf SKUs (Section 17 & Section 24 Q6)
        skus_data = [
            ("Milk 1L", "دودھ 1 لیٹر", "Dairy", 280.0, 12, sup_dairy),
            ("Yogurt 500g", "دہی 500 گرام", "Dairy", 180.0, 12, sup_dairy),
            ("Apple Juice 1L", "سیب کا جوس 1 لیٹر", "Beverages", 320.0, 12, sup_grocery),
            ("Orange Juice 1L", "مالٹے کا جوس 1 لیٹر", "Beverages", 320.0, 12, sup_grocery),
            ("White Bread 400g", "سفید ڈبل روٹی 400 گرام", "Bakery", 140.0, 10, sup_grocery),
            ("Corn Flakes 375g", "کارن فلیکس 375 گرام", "Breakfast", 650.0, 6, sup_grocery),
            ("Cooking Oil 1L", "کوکنگ آئل 1 لیٹر", "Pantry", 520.0, 12, sup_grocery),
            ("Basmati Rice 1kg", "باسمتی چاول 1 کلو", "Pantry", 380.0, 10, sup_grocery),
            ("Tomato Ketchup 500g", "ٹماٹو کیچپ 500 گرام", "Condiments", 290.0, 12, sup_grocery),
            ("Black Tea 400g", "کالی چائے 400 گرام", "Beverages", 750.0, 12, sup_grocery)
        ]

        created_skus = []
        for name_en, name_ur, cat, price, pack, supplier in skus_data:
            sku = SKU(name_en=name_en, name_ur=name_ur, category=cat, unit_price=price, pack_size=pack)
            db.add(sku)
            db.flush()
            created_skus.append(sku)
            # Map SKU to supplier
            sku_sup = SKUSupplier(sku_id=sku.sku_id, supplier_id=supplier.supplier_id, price=price, priority=1)
            db.add(sku_sup)

        # 7. Planogram for shelf1
        for zone_idx, sku in enumerate(created_skus[:10], start=1):
            pl = Planogram(shelf_id=shelf1.shelf_id, zone=zone_idx, sku_id=sku.sku_id, facings=1, depth_capacity=5)
            db.add(pl)

        # 8. Settings
        db.add(Setting(key="agent_enabled", value=True, scope="safety"))
        db.add(Setting(key="dry_run", value=True, scope="safety"))

        db.commit()
    except Exception as e:
        db.rollback()
        raise e
    finally:
        db.close()


if __name__ == "__main__":
    init_db(seed=True)
    print("Database initialized and seeded successfully.")
