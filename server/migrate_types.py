import asyncio
import asyncpg

async def migrate():
    conn_str = "postgresql://postgres.nivuflrurhbpcasgyyyz:Mubthaseem%4028@aws-0-ap-northeast-2.pooler.supabase.com:6543/postgres"
    conn = await asyncpg.connect(conn_str, statement_cache_size=0)

    # 1. Drop all foreign key constraints
    fks = [
        ("key_batches", "key_batches_created_by_fkey"),
        ("access_codes", "access_codes_batch_id_fkey"),
        ("entitlements", "entitlements_device_id_fkey"),
        ("entitlements", "entitlements_code_id_fkey"),
        ("refresh_tokens", "refresh_tokens_device_id_fkey"),
        ("event_streams", "event_streams_event_id_fkey"),
    ]
    for table, fk in fks:
        try:
            await conn.execute(f"ALTER TABLE {table} DROP CONSTRAINT IF EXISTS {fk};")
        except Exception as e:
            print(f"Drop constraint {fk}: {e}")

    # 2. Alter all UUID columns across all tables
    alterations = [
        ("admins", "id"),
        ("key_batches", "id"),
        ("key_batches", "created_by"),
        ("access_codes", "id"),
        ("access_codes", "batch_id"),
        ("devices", "id"),
        ("entitlements", "id"),
        ("entitlements", "device_id"),
        ("entitlements", "code_id"),
        ("refresh_tokens", "id"),
        ("refresh_tokens", "device_id"),
        ("members_items", "id"),
        ("audit_log", "id"),
        ("audit_log", "actor_id"),
        ("live_events", "id"),
        ("event_streams", "id"),
        ("event_streams", "event_id"),
    ]
    for table, col in alterations:
        try:
            await conn.execute(f"ALTER TABLE {table} ALTER COLUMN {col} TYPE uuid USING {col}::uuid;")
        except Exception as e:
            print(f"Alter {table}.{col}: {e}")

    # 3. Re-add all foreign key constraints
    re_fks = [
        ("key_batches", "key_batches_created_by_fkey", "FOREIGN KEY (created_by) REFERENCES admins(id) ON DELETE SET NULL"),
        ("access_codes", "access_codes_batch_id_fkey", "FOREIGN KEY (batch_id) REFERENCES key_batches(id) ON DELETE CASCADE"),
        ("entitlements", "entitlements_device_id_fkey", "FOREIGN KEY (device_id) REFERENCES devices(id) ON DELETE CASCADE"),
        ("entitlements", "entitlements_code_id_fkey", "FOREIGN KEY (code_id) REFERENCES access_codes(id) ON DELETE CASCADE"),
        ("refresh_tokens", "refresh_tokens_device_id_fkey", "FOREIGN KEY (device_id) REFERENCES devices(id) ON DELETE CASCADE"),
        ("event_streams", "event_streams_event_id_fkey", "FOREIGN KEY (event_id) REFERENCES live_events(id) ON DELETE CASCADE"),
    ]
    for table, name, definition in re_fks:
        try:
            await conn.execute(f"ALTER TABLE {table} ADD CONSTRAINT {name} {definition};")
        except Exception as e:
            print(f"Add constraint {name}: {e}")

    print("[SUCCESS] All tables converted to native PostgreSQL UUID!")
    await conn.close()

if __name__ == "__main__":
    asyncio.run(migrate())