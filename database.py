"""
Database module for SmartBus Intercity Bus Terminal Management & Standby Queue System.
Handles schema creation, parameterized queries, and realistic seed data for PITX operations.
"""

import sqlite3
import os
import hashlib
import random
from datetime import datetime, date

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bus_ticketing.db")


def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def generate_verification_code(ticket_id: int, passenger_name: str, seat_no: int) -> str:
    raw = f"PITX-{ticket_id}-{passenger_name}-{seat_no}-SECRET_SALT_2026"
    return "BTK-" + hashlib.sha256(raw.encode()).hexdigest()[:8].upper()


def init_db(force_reseed=False):
    db_exists = os.path.exists(DB_PATH)
    if db_exists and not force_reseed:
        return

    if os.path.exists(DB_PATH):
        try:
            os.remove(DB_PATH)
        except Exception:
            pass

    conn = get_connection()
    cur = conn.cursor()

    cur.executescript("""
    CREATE TABLE IF NOT EXISTS routes (
        route_id INTEGER PRIMARY KEY AUTOINCREMENT,
        origin TEXT NOT NULL,
        destination TEXT NOT NULL,
        departure_time TEXT NOT NULL,
        platform_bay TEXT NOT NULL,
        base_fare REAL NOT NULL,
        travel_duration TEXT NOT NULL,
        is_active INTEGER DEFAULT 1
    );

    CREATE TABLE IF NOT EXISTS buses (
        bus_id INTEGER PRIMARY KEY AUTOINCREMENT,
        bus_number TEXT UNIQUE NOT NULL,
        plate_number TEXT NOT NULL,
        bus_type TEXT NOT NULL,
        total_seats INTEGER DEFAULT 24,
        carrier_company TEXT NOT NULL,
        is_active INTEGER DEFAULT 1
    );

    CREATE TABLE IF NOT EXISTS passengers (
        passenger_id INTEGER PRIMARY KEY AUTOINCREMENT,
        full_name TEXT NOT NULL,
        contact_number TEXT NOT NULL,
        passenger_type TEXT NOT NULL CHECK(passenger_type IN ('Regular', 'Senior', 'PWD', 'Student')),
        concession_id_proof TEXT,
        created_at TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS tickets (
        ticket_id INTEGER PRIMARY KEY AUTOINCREMENT,
        route_id INTEGER NOT NULL,
        bus_id INTEGER NOT NULL,
        passenger_id INTEGER NOT NULL,
        travel_date TEXT NOT NULL,
        seat_number INTEGER NOT NULL CHECK(seat_number BETWEEN 1 AND 24),
        base_fare REAL NOT NULL,
        discount_amount REAL DEFAULT 0.0,
        final_fare REAL NOT NULL,
        status TEXT NOT NULL CHECK(status IN ('Confirmed', 'Cancelled', 'Boarded')),
        verification_code TEXT NOT NULL,
        is_chance_passenger INTEGER DEFAULT 0,
        issued_by TEXT DEFAULT 'Cashier-01',
        created_at TEXT NOT NULL,
        FOREIGN KEY (route_id) REFERENCES routes (route_id),
        FOREIGN KEY (bus_id) REFERENCES buses (bus_id),
        FOREIGN KEY (passenger_id) REFERENCES passengers (passenger_id)
    );

    -- Partial unique index guarantees mathematically zero double-bookings for active tickets
    CREATE UNIQUE INDEX IF NOT EXISTS idx_unique_active_seat
    ON tickets (route_id, bus_id, travel_date, seat_number)
    WHERE status = 'Confirmed';

    CREATE TABLE IF NOT EXISTS standby_queue (
        queue_id INTEGER PRIMARY KEY AUTOINCREMENT,
        route_id INTEGER NOT NULL,
        passenger_id INTEGER NOT NULL,
        travel_date TEXT NOT NULL,
        queue_number TEXT NOT NULL,
        priority_tier INTEGER NOT NULL CHECK(priority_tier IN (1, 2)), -- 1: Senior/PWD/Pregnant, 2: Regular
        enqueued_timestamp TEXT NOT NULL,
        status TEXT NOT NULL CHECK(status IN ('Waiting', 'Bumped', 'Expired', 'Cancelled')),
        assigned_seat_number INTEGER,
        bumped_timestamp TEXT,
        FOREIGN KEY (route_id) REFERENCES routes (route_id),
        FOREIGN KEY (passenger_id) REFERENCES passengers (passenger_id)
    );

    CREATE TABLE IF NOT EXISTS audit_logs (
        log_id INTEGER PRIMARY KEY AUTOINCREMENT,
        action_type TEXT NOT NULL,
        entity_name TEXT NOT NULL,
        entity_id TEXT,
        performed_by TEXT NOT NULL,
        timestamp TEXT NOT NULL,
        notes TEXT
    );
    """)

    # Seed Routes
    routes_data = [
        ("PITX Terminal", "Batangas City (Grand Terminal)", "08:30 AM", "Bay 04", 250.0, "2h 30m"),
        ("PITX Terminal", "Baguio City (Gov. Pack Road)", "09:15 AM", "Bay 07", 780.0, "5h 45m"),
        ("PITX Terminal", "Lucena City (Grand Central)", "10:00 AM", "Bay 02", 320.0, "3h 15m"),
        ("PITX Terminal", "Naga City (Bicol Central)", "11:30 AM", "Bay 11", 950.0, "8h 30m"),
        ("PITX Terminal", "Tagaytay City (Olivarez)", "01:00 PM", "Bay 05", 140.0, "1h 45m"),
        ("PITX Terminal", "Legazpi City (Grand Terminal)", "02:45 PM", "Bay 12", 1100.0, "10h 15m"),
    ]
    cur.executemany("""
        INSERT INTO routes (origin, destination, departure_time, platform_bay, base_fare, travel_duration)
        VALUES (?, ?, ?, ?, ?, ?)
    """, routes_data)

    # Seed Buses
    buses_data = [
        ("BUS-101", "NDB-4821", "Deluxe Aircon 2x2", 24, "ALPS The Bus, Inc."),
        ("BUS-102", "CAE-9912", "Executive Express 2x2", 24, "Victory Liner, Inc."),
        ("BUS-103", "WXZ-3104", "Deluxe Aircon 2x2", 24, "JAM Liner"),
        ("BUS-104", "RTY-7731", "Super Deluxe Sleeper", 24, "DLTB Co."),
        ("BUS-105", "BVC-2049", "Standard Aircon 2x2", 24, "San Agustin Transport"),
        ("BUS-106", "PLM-8890", "Executive Express 2x2", 24, "Philtranco Heritage"),
    ]
    cur.executemany("""
        INSERT INTO buses (bus_number, plate_number, bus_type, total_seats, carrier_company)
        VALUES (?, ?, ?, ?, ?)
    """, buses_data)

    today_str = date.today().isoformat()

    # Seed Sample Passengers and Confirmed Bookings
    sample_passengers = [
        ("Juan Dela Cruz", "09171234567", "Regular", None),
        ("Maria Santos", "09182345678", "Senior", "OSCA-MNL-2019-8812"),
        ("Angelo Reyes", "09203456789", "Student", "STU-DLSU-2024-001"),
        ("Teresa Mendoza", "09214567890", "PWD", "PWD-QC-44129"),
        ("Carlos Garcia", "09225678901", "Regular", None),
        ("Elena Bautista", "09236789012", "Regular", None),
        ("Roberto Diaz", "09247890123", "Senior", "OSCA-PAR-1092-33"),
        ("Clarissa Tan", "09258901234", "Regular", None),
        ("Fernando Ramos", "09269012345", "Student", "STU-UST-2023-994"),
        ("Luzviminda Ocampo", "09270123456", "Regular", None),
        ("Eduardo Flores", "09281234567", "Regular", None),
        ("Beatriz Lim", "09292345678", "PWD", "PWD-MAK-5582"),
        ("Ricardo Aquino", "09303456789", "Regular", None),
        ("Patricia Gomez", "09314567890", "Regular", None),
        ("Gabriel Villanueva", "09325678901", "Regular", None),
        ("Sofia Castillo", "09336789012", "Senior", "OSCA-CAV-3819"),
        ("Ramon Gutierrez", "09347890123", "Regular", None),
        ("Danilo Soriano", "09358901234", "Regular", None),
        ("Corazon Navarro", "09369012345", "Regular", None),
        ("Manuel Salvador", "09370123456", "Regular", None),
    ]

    for name, phone, p_type, proof in sample_passengers:
        cur.execute("""
            INSERT INTO passengers (full_name, contact_number, passenger_type, concession_id_proof, created_at)
            VALUES (?, ?, ?, ?, datetime('now', '-2 hours'))
        """, (name, phone, p_type, proof))

    # For Route 1 (Batangas), book Seats 1 to 18 (Leaving seats 19-24 open, or making Route 2 sold out)
    # Route 1: Base Fare 250
    for seat_num in range(1, 16):
        pid = seat_num
        cur.execute("SELECT passenger_type FROM passengers WHERE passenger_id = ?", (pid,))
        ptype = cur.fetchone()["passenger_type"]
        base_fare = 250.0
        disc = base_fare * 0.20 if ptype in ("Senior", "PWD", "Student") else 0.0
        final_fare = base_fare - disc
        
        cur.execute("""
            INSERT INTO tickets (route_id, bus_id, passenger_id, travel_date, seat_number,
                                 base_fare, discount_amount, final_fare, status, verification_code,
                                 is_chance_passenger, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'Confirmed', 'TEMP', 0, datetime('now', '-90 minutes'))
        """, (1, 1, pid, today_str, seat_num, base_fare, disc, final_fare))
        
        tid = cur.lastrowid
        cur.execute("SELECT full_name FROM passengers WHERE passenger_id = ?", (pid,))
        pname = cur.fetchone()["full_name"]
        code = generate_verification_code(tid, pname, seat_num)
        cur.execute("UPDATE tickets SET verification_code = ? WHERE ticket_id = ?", (code, tid))

    # For Route 2 (Baguio - 100% Sold Out to demonstrate Standby Chance Engine)
    # Book all 24 seats!
    baguio_passengers = [
        (f"Passenger {i}", f"0919000{i:04d}", "Senior" if i in (1, 2) else "Regular",
         f"OSCA-BAG-{i}" if i in (1, 2) else None)
        for i in range(1, 25)
    ]
    for bname, bphone, btype, bproof in baguio_passengers:
        cur.execute("""
            INSERT INTO passengers (full_name, contact_number, passenger_type, concession_id_proof, created_at)
            VALUES (?, ?, ?, ?, datetime('now', '-3 hours'))
        """, (bname, bphone, btype, bproof))
        pid = cur.lastrowid
        seat_no = int(bname.split()[1])
        base_fare = 780.0
        disc = base_fare * 0.20 if btype in ("Senior", "PWD", "Student") else 0.0
        final_fare = base_fare - disc
        
        cur.execute("""
            INSERT INTO tickets (route_id, bus_id, passenger_id, travel_date, seat_number,
                                 base_fare, discount_amount, final_fare, status, verification_code,
                                 is_chance_passenger, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'Confirmed', 'TEMP', 0, datetime('now', '-2 hours'))
        """, (2, 2, pid, today_str, seat_no, base_fare, disc, final_fare))
        tid = cur.lastrowid
        code = generate_verification_code(tid, bname, seat_no)
        cur.execute("UPDATE tickets SET verification_code = ? WHERE ticket_id = ?", (code, tid))

    # Seed Standby Queue for Route 2 (Baguio)
    standby_candidates = [
        ("Lola Remedios Pascual", "09151112233", "Senior", "OSCA-VAL-9912", 1), # Tier 1 Priority
        ("Kuya Arnel Magpantay", "09172223344", "Regular", None, 2),            # Tier 2 Regular
        ("Ate Jessica Morales", "09203334455", "Regular", None, 2),             # Tier 2 Regular
        ("Lolo Vicente Cruz", "09214445566", "Senior", "OSCA-BUL-5120", 1),     # Tier 1 Priority
        ("Mark Anthony Beltran", "09225556677", "Student", "STU-PUP-2025-11", 2),# Tier 2 Regular
    ]

    for idx, (sname, sphone, stype, sproof, tier) in enumerate(standby_candidates, 1):
        cur.execute("""
            INSERT INTO passengers (full_name, contact_number, passenger_type, concession_id_proof, created_at)
            VALUES (?, ?, ?, ?, datetime('now', '-45 minutes'))
        """, (sname, sphone, stype, sproof))
        spid = cur.lastrowid
        q_num = f"#Q-{idx:02d}"
        cur.execute("""
            INSERT INTO standby_queue (route_id, passenger_id, travel_date, queue_number, priority_tier,
                                       enqueued_timestamp, status)
            VALUES (?, ?, ?, ?, ?, datetime('now', '-40 minutes'), 'Waiting')
        """, (2, spid, today_str, q_num, tier))

    # Audit Logs
    cur.execute("""
        INSERT INTO audit_logs (action_type, entity_name, entity_id, performed_by, timestamp, notes)
        VALUES ('SYSTEM_INIT', 'DATABASE', 'ALL', 'SystemAdmin', datetime('now', '-4 hours'), 'PITX Terminal Database Initialized with 6 Intercity Corridors.')
    """)
    cur.execute("""
        INSERT INTO audit_logs (action_type, entity_name, entity_id, performed_by, timestamp, notes)
        VALUES ('ROUTE_CAPACITY_REACHED', 'TRIP_BAGUIO', '2', 'Dispatcher-02', datetime('now', '-1 hour'), 'Route 2 (Baguio 09:15 AM) 100% booked. Standby Queue activated.')
    """)

    conn.commit()
    conn.close()
    print("Database bus_ticketing.db initialized and pre-populated successfully!")


if __name__ == "__main__":
    init_db(force_reseed=True)
