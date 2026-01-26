import sqlite3

conn = sqlite3.connect('data/psyco_app.db')
cursor = conn.cursor()

# Add new columns for chunked recording support
try:
    cursor.execute('ALTER TABLE sessions ADD COLUMN is_chunked BOOLEAN DEFAULT 0')
    print("Added: is_chunked")
except sqlite3.OperationalError as e:
    print(f"Skipped is_chunked: {e}")

try:
    cursor.execute('ALTER TABLE sessions ADD COLUMN chunks_total INTEGER DEFAULT 0')
    print("Added: chunks_total")
except sqlite3.OperationalError as e:
    print(f"Skipped chunks_total: {e}")

try:
    cursor.execute('ALTER TABLE sessions ADD COLUMN chunks_transcribed INTEGER DEFAULT 0')
    print("Added: chunks_transcribed")
except sqlite3.OperationalError as e:
    print(f"Skipped chunks_transcribed: {e}")

try:
    cursor.execute('ALTER TABLE sessions ADD COLUMN partial_transcription TEXT DEFAULT ""')
    print("Added: partial_transcription")
except sqlite3.OperationalError as e:
    print(f"Skipped partial_transcription: {e}")

conn.commit()
conn.close()
print("\n✅ Migration completed!")
