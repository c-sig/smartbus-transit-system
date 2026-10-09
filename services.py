"""
Business Logic & Service Layer for SmartBus Terminal Management System.
Implements:
- Algorithmic FIFO Standby Queueing
- Priority Tiering (Tier 1: Senior/PWD, Tier 2: Regular)
- Automated Priority Bumping upon Seat Vacation (Cancellation or No-Show)
- 20% Concession Discount Verification
- Cryptographic SHA-256 Boarding Pass Verification
"""

import sqlite3
from datetime import datetime, date
from database import get_connection, generate_verification_code


class SmartBusService:
    @staticmethod
    def get_routes():
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("SELECT * FROM routes WHERE is_active = 1 ORDER BY route_id ASC")
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()
        return rows

    @staticmethod
    def get_route_by_id(route_id):
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("SELECT * FROM routes WHERE route_id = ?", (route_id,))
        row = cur.fetchone()
        conn.close()
        return dict(row) if row else None

    @staticmethod
    def get_bus_for_route(route_id):
        conn = get_connection()
        cur = conn.cursor()
        # In this configuration, bus_id = route_id
        cur.execute("SELECT * FROM buses WHERE bus_id = ?", (route_id,))
        row = cur.fetchone()
        if not row:
            cur.execute("SELECT * FROM buses LIMIT 1")
            row = cur.fetchone()
        conn.close()
        return dict(row) if row else None

    @staticmethod
    def get_seat_matrix(route_id, travel_date=None):
        if not travel_date:
            travel_date = date.today().isoformat()
        
        conn = get_connection()
        cur = conn.cursor()
        
        cur.execute("""
            SELECT t.seat_number, t.ticket_id, t.status, t.is_chance_passenger,
                   p.full_name, p.passenger_type, t.final_fare, t.verification_code
            FROM tickets t
            JOIN passengers p ON t.passenger_id = p.passenger_id
            WHERE t.route_id = ? AND t.travel_date = ? AND t.status = 'Confirmed'
        """, (route_id, travel_date))
        
        booked_seats = {}
        for r in cur.fetchall():
            booked_seats[r["seat_number"]] = dict(r)

        seats_status = {}
        for seat_no in range(1, 25):
            if seat_no in booked_seats:
                info = booked_seats[seat_no]
                if info["is_chance_passenger"] == 1:
                    seats_status[seat_no] = {
                        "status": "Chance",
                        "color": "#9333EA", # Purple
                        "info": info
                    }
                else:
                    seats_status[seat_no] = {
                        "status": "Occupied",
                        "color": "#DC2626", # Red
                        "info": info
                    }
            else:
                # Row 1 (Seats 1, 2, 3, 4) are designated Priority seats
                if seat_no in (1, 2, 3, 4):
                    seats_status[seat_no] = {
                        "status": "Priority",
                        "color": "#D97706", # Amber
                        "info": None
                    }
                else:
                    seats_status[seat_no] = {
                        "status": "Available",
                        "color": "#16A34A", # Green
                        "info": None
                    }

        conn.close()
        return seats_status

    @staticmethod
    def book_seat(route_id, full_name, contact_number, passenger_type,
                  concession_proof, seat_number, travel_date=None, issued_by="Cashier-01"):
        if not travel_date:
            travel_date = date.today().isoformat()

        conn = get_connection()
        cur = conn.cursor()

        try:
            cur.execute("SELECT base_fare FROM routes WHERE route_id = ?", (route_id,))
            route = cur.fetchone()
            if not route:
                return False, "Selected route does not exist."
            base_fare = float(route["base_fare"])

            # Row 1 Priority check
            if seat_number in (1, 2, 3, 4) and passenger_type == "Regular":
                return False, "Row 1 (Seats 01-04) is strictly reserved for Senior Citizens, PWDs, and pregnant commuters."

            # Calculate concession
            discount = 0.0
            if passenger_type in ("Senior", "PWD", "Student"):
                if not concession_proof or not concession_proof.strip():
                    return False, f"Official ID proof is mandatory for {passenger_type} 20% concession."
                discount = base_fare * 0.20
            final_fare = base_fare - discount

            # Insert passenger
            cur.execute("""
                INSERT INTO passengers (full_name, contact_number, passenger_type, concession_id_proof, created_at)
                VALUES (?, ?, ?, ?, datetime('now'))
            """, (full_name.strip(), contact_number.strip(), passenger_type, concession_proof.strip() if concession_proof else None))
            passenger_id = cur.lastrowid

            bus_id = route_id # Assigned bus

            # Insert ticket
            cur.execute("""
                INSERT INTO tickets (route_id, bus_id, passenger_id, travel_date, seat_number,
                                     base_fare, discount_amount, final_fare, status, verification_code,
                                     is_chance_passenger, issued_by, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'Confirmed', 'TEMP', 0, ?, datetime('now'))
            """, (route_id, bus_id, passenger_id, travel_date, seat_number, base_fare, discount, final_fare, issued_by))
            ticket_id = cur.lastrowid

            vcode = generate_verification_code(ticket_id, full_name, seat_number)
            cur.execute("UPDATE tickets SET verification_code = ? WHERE ticket_id = ?", (vcode, ticket_id))

            # Audit log
            cur.execute("""
                INSERT INTO audit_logs (action_type, entity_name, entity_id, performed_by, timestamp, notes)
                VALUES ('TICKET_ISSUED', 'TICKET', ?, ?, datetime('now'), ?)
            """, (str(ticket_id), issued_by, f"Seat #{seat_number:02d} booked for {full_name} ({passenger_type}) - Fare: ₱{final_fare:.2f}"))

            conn.commit()
            return True, {
                "ticket_id": ticket_id,
                "verification_code": vcode,
                "seat_number": seat_number,
                "passenger_name": full_name,
                "passenger_type": passenger_type,
                "final_fare": final_fare,
                "base_fare": base_fare,
                "discount": discount,
                "travel_date": travel_date
            }
        except sqlite3.IntegrityError as e:
            conn.rollback()
            return False, f"Seat #{seat_number:02d} is already occupied or double-booked: {e}"
        except Exception as e:
            conn.rollback()
            return False, str(e)
        finally:
            conn.close()

    @staticmethod
    def enqueue_standby_passenger(route_id, full_name, contact_number, passenger_type,
                                  concession_proof, travel_date=None, enqueued_by="Cashier-01"):
        if not travel_date:
            travel_date = date.today().isoformat()

        conn = get_connection()
        cur = conn.cursor()

        try:
            # Determine Tier (Tier 1: Senior, PWD; Tier 2: Regular, Student)
            priority_tier = 1 if passenger_type in ("Senior", "PWD") else 2

            # Count existing queue for numbering
            cur.execute("""
                SELECT COUNT(*) as q_count FROM standby_queue
                WHERE route_id = ? AND travel_date = ?
            """, (route_id, travel_date))
            q_count = cur.fetchone()["q_count"] + 1
            queue_num = f"#Q-{q_count:02d}"

            # Insert passenger
            cur.execute("""
                INSERT INTO passengers (full_name, contact_number, passenger_type, concession_id_proof, created_at)
                VALUES (?, ?, ?, ?, datetime('now'))
            """, (full_name.strip(), contact_number.strip(), passenger_type, concession_proof.strip() if concession_proof else None))
            passenger_id = cur.lastrowid

            # Insert standby queue
            cur.execute("""
                INSERT INTO standby_queue (route_id, passenger_id, travel_date, queue_number,
                                           priority_tier, enqueued_timestamp, status)
                VALUES (?, ?, ?, ?, ?, datetime('now'), 'Waiting')
            """, (route_id, passenger_id, travel_date, queue_num, priority_tier))
            queue_id = cur.lastrowid

            # Audit log
            cur.execute("""
                INSERT INTO audit_logs (action_type, entity_name, entity_id, performed_by, timestamp, notes)
                VALUES ('STANDBY_ENQUEUED', 'STANDBY_QUEUE', ?, ?, datetime('now'), ?)
            """, (str(queue_id), enqueued_by, f"Standby slip {queue_num} issued to {full_name} (Tier {priority_tier})"))

            conn.commit()
            return True, {
                "queue_id": queue_id,
                "queue_number": queue_num,
                "priority_tier": priority_tier,
                "passenger_name": full_name,
                "passenger_type": passenger_type,
                "contact_number": contact_number,
                "travel_date": travel_date
            }
        except Exception as e:
            conn.rollback()
            return False, str(e)
        finally:
            conn.close()

    @staticmethod
    def cancel_ticket(ticket_id, cancelled_by="Cashier-01"):
        conn = get_connection()
        cur = conn.cursor()

        try:
            cur.execute("""
                SELECT t.*, p.full_name, p.passenger_type, p.contact_number, r.destination, r.base_fare
                FROM tickets t
                JOIN passengers p ON t.passenger_id = p.passenger_id
                JOIN routes r ON t.route_id = r.route_id
                WHERE t.ticket_id = ?
            """, (ticket_id,))
            ticket = cur.fetchone()
            if not ticket:
                return False, "Ticket not found.", None
            if ticket["status"] != "Confirmed":
                return False, f"Ticket #{ticket_id} is already {ticket['status']}.", None

            seat_no = ticket["seat_number"]
            route_id = ticket["route_id"]
            travel_date = ticket["travel_date"]
            bus_id = ticket["bus_id"]
            p_name = ticket["full_name"]

            # Cancel ticket
            cur.execute("UPDATE tickets SET status = 'Cancelled' WHERE ticket_id = ?", (ticket_id,))

            cur.execute("""
                INSERT INTO audit_logs (action_type, entity_name, entity_id, performed_by, timestamp, notes)
                VALUES ('TICKET_CANCELLED', 'TICKET', ?, ?, datetime('now'), ?)
            """, (str(ticket_id), cancelled_by, f"Ticket #{ticket_id} for {p_name} (Seat #{seat_no:02d}) cancelled. Seat released."))

            # Trigger automated Priority Standby Bumping!
            # Query top waiting standby passenger ordered by priority_tier ASC, enqueued_timestamp ASC
            cur.execute("""
                SELECT sq.queue_id, sq.passenger_id, sq.queue_number, sq.priority_tier,
                       p.full_name, p.contact_number, p.passenger_type, p.concession_id_proof
                FROM standby_queue sq
                JOIN passengers p ON sq.passenger_id = p.passenger_id
                WHERE sq.route_id = ? AND sq.travel_date = ? AND sq.status = 'Waiting'
                ORDER BY sq.priority_tier ASC, sq.enqueued_timestamp ASC
                LIMIT 1
            """, (route_id, travel_date))
            standby_cand = cur.fetchone()

            bumped_info = None
            if standby_cand:
                sq_id = standby_cand["queue_id"]
                cand_pid = standby_cand["passenger_id"]
                cand_name = standby_cand["full_name"]
                cand_type = standby_cand["passenger_type"]
                q_num = standby_cand["queue_number"]
                
                # Base fare and discount for standby passenger
                base_fare = float(ticket["base_fare"])
                disc = base_fare * 0.20 if cand_type in ("Senior", "PWD", "Student") else 0.0
                final_fare = base_fare - disc

                # Update Standby Queue
                cur.execute("""
                    UPDATE standby_queue
                    SET status = 'Bumped', assigned_seat_number = ?, bumped_timestamp = datetime('now')
                    WHERE queue_id = ?
                """, (seat_no, sq_id))

                # Create new confirmed ticket for bumped chance passenger
                cur.execute("""
                    INSERT INTO tickets (route_id, bus_id, passenger_id, travel_date, seat_number,
                                         base_fare, discount_amount, final_fare, status, verification_code,
                                         is_chance_passenger, issued_by, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'Confirmed', 'TEMP', 1, ?, datetime('now'))
                """, (route_id, bus_id, cand_pid, travel_date, seat_no, base_fare, disc, final_fare, cancelled_by))
                new_tid = cur.lastrowid
                new_vcode = generate_verification_code(new_tid, cand_name, seat_no)
                cur.execute("UPDATE tickets SET verification_code = ? WHERE ticket_id = ?", (new_vcode, new_tid))

                cur.execute("""
                    INSERT INTO audit_logs (action_type, entity_name, entity_id, performed_by, timestamp, notes)
                    VALUES ('STANDBY_AUTO_BUMPED', 'STANDBY_QUEUE', ?, ?, datetime('now'), ?)
                """, (str(sq_id), cancelled_by, f"Standby {q_num} ({cand_name}, Tier {standby_cand['priority_tier']}) AUTO-BUMPED into freed Seat #{seat_no:02d}! Ticket #{new_tid} generated."))

                bumped_info = {
                    "queue_number": q_num,
                    "passenger_name": cand_name,
                    "passenger_type": cand_type,
                    "seat_number": seat_no,
                    "ticket_id": new_tid,
                    "verification_code": new_vcode,
                    "final_fare": final_fare,
                    "priority_tier": standby_cand["priority_tier"]
                }

            conn.commit()
            return True, f"Ticket #{ticket_id} successfully cancelled. Seat #{seat_no:02d} released.", bumped_info
        except Exception as e:
            conn.rollback()
            return False, str(e), None
        finally:
            conn.close()

    @staticmethod
    def get_kpis():
        conn = get_connection()
        cur = conn.cursor()
        today_str = date.today().isoformat()

        cur.execute("SELECT COUNT(*) as count, COALESCE(SUM(final_fare), 0) as total_rev FROM tickets WHERE travel_date = ? AND status = 'Confirmed'", (today_str,))
        t_row = cur.fetchone()
        tickets_sold = t_row["count"]
        gross_rev = t_row["total_rev"]

        cur.execute("SELECT COUNT(*) as count FROM standby_queue WHERE travel_date = ? AND status = 'Waiting'", (today_str,))
        standby_waiting = cur.fetchone()["count"]

        cur.execute("SELECT COUNT(*) as count FROM standby_queue WHERE travel_date = ? AND status = 'Bumped'", (today_str,))
        standby_bumped = cur.fetchone()["count"]

        cur.execute("SELECT COUNT(*) as count FROM tickets WHERE travel_date = ? AND status = 'Cancelled'", (today_str,))
        cancelled_count = cur.fetchone()["count"]

        conn.close()
        return {
            "tickets_sold": tickets_sold,
            "gross_revenue": gross_rev,
            "standby_waiting": standby_waiting,
            "standby_bumped": standby_bumped,
            "cancelled_count": cancelled_count
        }

    @staticmethod
    def get_all_manifest(search_query=None):
        conn = get_connection()
        cur = conn.cursor()
        today_str = date.today().isoformat()

        sql = """
            SELECT t.ticket_id, t.seat_number, t.final_fare, t.status, t.is_chance_passenger,
                   t.verification_code, t.created_at, p.full_name, p.contact_number, p.passenger_type,
                   r.destination, r.departure_time, r.platform_bay
            FROM tickets t
            JOIN passengers p ON t.passenger_id = p.passenger_id
            JOIN routes r ON t.route_id = r.route_id
            WHERE t.travel_date = ?
        """
        params = [today_str]
        if search_query and search_query.strip():
            sql += " AND (p.full_name LIKE ? OR t.verification_code LIKE ? OR r.destination LIKE ? OR CAST(t.ticket_id AS TEXT) LIKE ?)"
            q = f"%{search_query.strip()}%"
            params.extend([q, q, q, q])

        sql += " ORDER BY t.ticket_id DESC"
        cur.execute(sql, params)
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()
        return rows

    @staticmethod
    def get_standby_manifest(search_query=None):
        conn = get_connection()
        cur = conn.cursor()
        today_str = date.today().isoformat()

        sql = """
            SELECT sq.queue_id, sq.queue_number, sq.priority_tier, sq.status, sq.assigned_seat_number,
                   sq.enqueued_timestamp, p.full_name, p.contact_number, p.passenger_type,
                   r.destination, r.departure_time
            FROM standby_queue sq
            JOIN passengers p ON sq.passenger_id = p.passenger_id
            JOIN routes r ON sq.route_id = r.route_id
            WHERE sq.travel_date = ?
        """
        params = [today_str]
        if search_query and search_query.strip():
            sql += " AND (p.full_name LIKE ? OR sq.queue_number LIKE ? OR r.destination LIKE ?)"
            q = f"%{search_query.strip()}%"
            params.extend([q, q, q])

        sql += " ORDER BY sq.priority_tier ASC, sq.enqueued_timestamp ASC"
        cur.execute(sql, params)
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()
        return rows

    @staticmethod
    def get_audit_logs(limit=50):
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("SELECT * FROM audit_logs ORDER BY log_id DESC LIMIT ?", (limit,))
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()
        return rows
