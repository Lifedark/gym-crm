from app import app, mongo, bcrypt
from datetime import datetime, timedelta
from bson.objectid import ObjectId

with app.app_context():
    existing = mongo.db.users.find_one({"username": "admin"})
    if existing:
        print("Admin already exists. Skipping user seed.")
    else:
        hashed = bcrypt.generate_password_hash("admin123").decode("utf-8")
        mongo.db.users.insert_one({
            "username": "admin",
            "password": hashed,
            "name": "Administrator",
            "role": "admin",
            "created_at": datetime.now(),
            "last_login": None
        })
        print("Created admin user: admin / admin123")

    types_count = mongo.db.membership_types.count_documents({})
    if types_count > 0:
        print(f"Already {types_count} membership types. Skipping type seed.")
    else:
        types = [
            {
                "name": "Miesięczny",
                "type": "period",
                "duration_days": 30,
                "price": 120,
                "description": "Karnet miesięczny – nielimitowane wejścia",
                "created_at": datetime.now()
            },
            {
                "name": "Kwartalny",
                "type": "period",
                "duration_days": 90,
                "price": 300,
                "description": "Karnet kwartalny – oszczędzasz 60 zł",
                "created_at": datetime.now()
            },
            {
                "name": "Roczny",
                "type": "period",
                "duration_days": 365,
                "price": 960,
                "description": "Karnet roczny – najlepsza cena",
                "created_at": datetime.now()
            },
            {
                "name": "10 wejść",
                "type": "entries",
                "entries_count": 10,
                "price": 80,
                "description": "Pakiet 10 wejść",
                "created_at": datetime.now()
            },
            {
                "name": "20 wejść",
                "type": "entries",
                "entries_count": 20,
                "price": 140,
                "description": "Pakiet 20 wejść",
                "created_at": datetime.now()
            },
            {
                "name": "Próbny",
                "type": "entries",
                "entries_count": 1,
                "price": 20,
                "description": "Jednorazowe wejście próbne",
                "created_at": datetime.now()
            }
        ]
        mongo.db.membership_types.insert_many(types)
        print(f"Created {len(types)} membership types.")

    member_count = mongo.db.members.count_documents({})
    if member_count > 0:
        print(f"Already {member_count} members. Skipping member seed.")
    else:
        monthly = mongo.db.membership_types.find_one({"name": "Miesięczny"})
        ten_entries = mongo.db.membership_types.find_one({"name": "10 wejść"})

        from uuid import uuid4

        sample_members = [
            {
                "name": "Jan Kowalski",
                "phone": "500123456",
                "email": "jan@example.com",
                "membership_type_id": str(monthly["_id"]),
                "qr_code": str(uuid4())[:8].upper(),
                "status": "active",
                "start_date": datetime.now(),
                "end_date": datetime.now() + timedelta(days=30),
                "entries_left": None,
                "total_entries": None,
                "notes": "",
                "created_at": datetime.now(),
                "created_by": None
            },
            {
                "name": "Anna Nowak",
                "phone": "501234567",
                "email": "anna@example.com",
                "membership_type_id": str(ten_entries["_id"]),
                "qr_code": str(uuid4())[:8].upper(),
                "status": "active",
                "start_date": datetime.now(),
                "end_date": None,
                "entries_left": 10,
                "total_entries": 10,
                "notes": "Preferuje treningi poranne",
                "created_at": datetime.now(),
                "created_by": None
            },
            {
                "name": "Piotr Wiśniewski",
                "phone": "502345678",
                "email": "piotr@example.com",
                "membership_type_id": None,
                "qr_code": str(uuid4())[:8].upper(),
                "status": "expired",
                "start_date": datetime.now() - timedelta(days=60),
                "end_date": datetime.now() - timedelta(days=30),
                "entries_left": None,
                "total_entries": None,
                "notes": "",
                "created_at": datetime.now(),
                "created_by": None
            }
        ]
        mongo.db.members.insert_many(sample_members)
        print(f"Created {len(sample_members)} sample members.")

        # Add some sample checkins
        for i in range(5):
            member = mongo.db.members.find_one({"name": "Jan Kowalski"})
            if member:
                mongo.db.checkins.insert_one({
                    "member_id": str(member["_id"]),
                    "checked_by": None,
                    "timestamp": datetime.now() - timedelta(hours=i * 2),
                    "method": "scan" if i % 2 == 0 else "manual"
                })

        member2 = mongo.db.members.find_one({"name": "Anna Nowak"})
        if member2:
            mongo.db.checkins.insert_one({
                "member_id": str(member2["_id"]),
                "checked_by": None,
                "timestamp": datetime.now() - timedelta(hours=1),
                "method": "scan"
            })
        print("Added sample checkins.")

    print("\nSeed completed!")
    print("Login: admin / admin123")
