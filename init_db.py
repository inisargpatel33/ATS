import psycopg2
from settings import DATABASE_URL

def initialize_database():
    print("Connecting to database...")
    conn = psycopg2.connect(DATABASE_URL)
    cursor = conn.cursor()
    
    try:
        print("Reading schema.sql...")
        with open("schema.sql", "r") as file:
            schema_sql = file.read()
            
        print("Executing master schema...")
        cursor.execute(schema_sql)
        conn.commit()
        print("✅ Database successfully initialized with all constraints!")
        
    except Exception as e:
        print("❌ FAILED TO INITIALIZE DATABASE")
        print(e)
        conn.rollback()
    finally:
        cursor.close()
        conn.close()

if __name__ == "__main__":
    initialize_database()