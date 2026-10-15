
from sqlalchemy import func, select

from app.database.session import SessionLocal
from app.database.models import POI


with SessionLocal() as db:
    total = db.scalar(select(func.count()).select_from(POI))
    print(f"\nTotal POIs in database: {total}")

    cities = db.execute(
        select(POI.city, func.count())
        .group_by(POI.city)
        .order_by(func.count().desc())
    ).all()

    print("\nPOIs by city:")
    for city, count in cities:
        print(f"  {city!r}: {count}")

    categories = db.execute(
        select(POI.category, func.count())
        .group_by(POI.category)
        .order_by(func.count().desc())
    ).all()

    print("\nPOIs by category:")
    for category, count in categories:
        print(f"  {category!r}: {count}")

    print("\nSample POIs:")
    samples = db.scalars(select(POI).limit(10)).all()

    for poi in samples:
        print(
            f"ID={poi.id}, name={poi.name!r}, "
            f"city={poi.city!r}, category={poi.category!r}"
        )
