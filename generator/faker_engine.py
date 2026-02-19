import random
from faker import Faker

fake = Faker()


def generate_single(col_name: str, col_type: str, row_index: int):
    """Generate one fake value based on column type + name context."""
    t = col_type.lower().strip()
    n = col_name.lower().strip()

    # string — context-aware by column name
    if t == "string":
        if "name" in n and "first" in n:
            return fake.first_name()
        if "name" in n and "last" in n:
            return fake.last_name()
        if "name" in n:
            return fake.name()
        if "title" in n:
            return fake.catch_phrase()
        if "description" in n or "desc" in n:
            return fake.text(100)
        if "status" in n:
            return random.choice(["Active", "Inactive", "Pending", "Completed"])
        if "category" in n:
            return random.choice(["Electronics", "Clothing", "Food", "Books", "Sports", "Health"])
        return fake.word()

    # number — context-aware
    if t == "number":
        if "age" in n:
            return random.randint(18, 99)
        if "id" in n:
            return row_index + 1
        if any(w in n for w in ["price", "cost", "amount", "salary", "revenue"]):
            return round(random.uniform(10, 10000), 2)
        if "year" in n:
            return random.randint(1950, 2025)
        if "quantity" in n or "stock" in n or "count" in n:
            return random.randint(0, 500)
        return random.randint(1, 1000)

    if t == "boolean":
        return fake.boolean()

    if t == "date":
        return fake.date().strftime("%Y-%m-%d") if hasattr(fake.date(), "strftime") else str(fake.date())

    if t == "email":
        return fake.email()

    if t == "phone number":
        return fake.phone_number()

    if t == "date of birth":
        return fake.date_of_birth(minimum_age=18, maximum_age=90).strftime("%Y-%m-%d")

    if t == "name":
        if "first" in n or "fname" in n:
            return fake.first_name()
        if "last" in n or "lname" in n:
            return fake.last_name()
        return fake.name()

    if t == "first name":
        return fake.first_name()

    if t == "last name":
        return fake.last_name()

    if t == "full name":
        return fake.name()

    if t == "gender":
        return random.choice(["Male", "Female", "Other"])

    if t == "ssn":
        return fake.ssn()

    if t == "address":
        return fake.address().replace("\n", ", ")

    if t == "city":
        return fake.city()

    if t == "country":
        return fake.country()

    if t == "state":
        return fake.state()

    if t in ("postal code", "zip code"):
        return fake.postcode()

    if t == "latitude":
        return round(float(fake.latitude()), 6)

    if t == "longitude":
        return round(float(fake.longitude()), 6)

    if t == "company name":
        return fake.company()

    if t == "job title":
        return fake.job()

    if t == "department":
        return random.choice([
            "Engineering", "Marketing", "Sales", "Human Resources",
            "Finance", "Operations", "Customer Service", "IT",
            "Legal", "Research & Development",
        ])

    if t == "employee id":
        return f"EMP-{row_index + 1:04d}"

    if t == "currency":
        return f"${random.uniform(1, 10000):.2f}"

    if t == "credit card":
        return fake.credit_card_number()

    if t == "url":
        return fake.url()

    if t == "ip address":
        return fake.ipv4()

    if t == "username":
        return fake.user_name()

    if t == "password":
        return fake.password(length=12)

    if t == "domain":
        return fake.domain_name()

    if t == "mac address":
        return fake.mac_address()

    if t == "paragraph":
        return fake.paragraph(nb_sentences=3)

    if t == "sentence":
        return fake.sentence()

    if t == "word":
        return fake.word()

    if t == "uuid":
        return str(fake.uuid4())

    if t == "slug":
        return fake.slug()

    if t == "description":
        return fake.text(100)

    if t == "image url":
        return f"https://picsum.photos/{random.randint(200, 800)}/{random.randint(200, 800)}"

    if t == "color":
        return fake.color_name()

    if t in ("integer", "int"):
        return random.randint(1, 1000)

    if t in ("float", "decimal"):
        return round(random.uniform(0, 100), 2)

    if t in ("datetime", "timestamp"):
        return fake.date_time().strftime("%Y-%m-%d %H:%M:%S")

    if t == "time":
        return fake.time()

    if t == "street":
        return fake.street_address()

    if t == "iban":
        return fake.iban()

    if t == "bitcoin address":
        return fake.cryptocurrency_code()

    if t == "price":
        return round(random.uniform(1, 1000), 2)

    # fallback
    return fake.word()


def generate(columns: list, rows: int) -> list:
    """Generate full dataset using Faker. columns = [{"name": ..., "type": ...}]"""
    records = []
    for i in range(rows):
        row = {}
        for col in columns:
            row[col["name"]] = generate_single(col["name"], col["type"], i)
        records.append(row)
    return records
