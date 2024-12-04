# app.py
from flask import Flask, render_template, request, redirect, url_for, flash, session
from datetime import datetime, timedelta
import sqlite3
import random
import string
import os

app = Flask(__name__)
app.secret_key = os.urandom(24)

class BadmintonBookingSystem:
    def __init__(self):
        self.conn = sqlite3.connect('badminton_booking.db', check_same_thread=False)
        self.cursor = self.conn.cursor()
        self.setup_database()
        self.current_user = None

    def setup_database(self):
        # Create Users table
        self.cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL,
            phone TEXT
        )''')

        # Create Courts table
        self.cursor.execute('''
        CREATE TABLE IF NOT EXISTS courts (
            court_id INTEGER PRIMARY KEY AUTOINCREMENT,
            court_name TEXT NOT NULL,
            hourly_rate DECIMAL(10,2) NOT NULL
        )''')

        # Create Bookings table
        self.cursor.execute('''
        CREATE TABLE IF NOT EXISTS bookings (
            booking_id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            court_id INTEGER,
            booking_date DATE NOT NULL,
            start_time TIME NOT NULL,
            end_time TIME NOT NULL,
            status TEXT DEFAULT 'pending',
            FOREIGN KEY (user_id) REFERENCES users (user_id),
            FOREIGN KEY (court_id) REFERENCES courts (court_id)
        )''')

        # Create Payments table
        self.cursor.execute('''
        CREATE TABLE IF NOT EXISTS payments (
            payment_id INTEGER PRIMARY KEY AUTOINCREMENT,
            booking_id INTEGER,
            amount DECIMAL(10,2) NOT NULL,
            payment_date DATETIME DEFAULT CURRENT_TIMESTAMP,
            transaction_id TEXT UNIQUE,
            status TEXT DEFAULT 'pending',
            FOREIGN KEY (booking_id) REFERENCES bookings (booking_id)
        )''')

        # Insert sample courts if they don't exist
        self.cursor.execute('SELECT COUNT(*) FROM courts')
        if self.cursor.fetchone()[0] == 0:
            sample_courts = [
                ('Court A', 25.00),
                ('Court B', 25.00),
                ('Court C', 30.00),
                ('Court D', 30.00)
            ]
            self.cursor.executemany('INSERT INTO courts (court_name, hourly_rate) VALUES (?, ?)', 
                                  sample_courts)
        
        self.conn.commit()

    def register_user(self, username, password, email, phone):
        try:
            self.cursor.execute('''
            INSERT INTO users (username, password, email, phone)
            VALUES (?, ?, ?, ?)
            ''', (username, password, email, phone))
            self.conn.commit()
            return True
        except sqlite3.IntegrityError:
            return False

    def login(self, username, password):
        self.cursor.execute('''
        SELECT user_id, username FROM users
        WHERE username = ? AND password = ?
        ''', (username, password))
        user = self.cursor.fetchone()
        if user:
            self.current_user = {'user_id': user[0], 'username': user[1]}
            return True
        return False

    def get_available_courts(self, date, start_time, end_time):
        self.cursor.execute('''
        SELECT c.court_id, c.court_name, c.hourly_rate
        FROM courts c
        WHERE c.court_id NOT IN (
            SELECT court_id FROM bookings
            WHERE booking_date = ?
            AND (
                (start_time <= ? AND end_time > ?) OR
                (start_time < ? AND end_time >= ?) OR
                (start_time >= ? AND end_time <= ?)
            )
            AND status != 'cancelled'
        )
        ''', (date, start_time, start_time, end_time, end_time, start_time, end_time))
        return self.cursor.fetchall()

    def create_booking(self, court_id, date, start_time, end_time):
        try:
            # Create booking
            self.cursor.execute('''
            INSERT INTO bookings (user_id, court_id, booking_date, start_time, end_time)
            VALUES (?, ?, ?, ?, ?)
            ''', (session['user_id'], court_id, date, start_time, end_time))
            
            booking_id = self.cursor.lastrowid

            # Calculate payment amount
            self.cursor.execute('SELECT hourly_rate FROM courts WHERE court_id = ?', (court_id,))
            hourly_rate = self.cursor.fetchone()[0]
            
            # Calculate duration in hours
            start = datetime.strptime(start_time, '%H:%M')
            end = datetime.strptime(end_time, '%H:%M')
            duration = (end - start).seconds / 3600
            amount = hourly_rate * duration

            # Generate random transaction ID
            transaction_id = ''.join(random.choices(string.ascii_uppercase + string.digits, k=10))

            # Create payment record
            self.cursor.execute('''
            INSERT INTO payments (booking_id, amount, transaction_id)
            VALUES (?, ?, ?)
            ''', (booking_id, amount, transaction_id))

            self.conn.commit()
            return booking_id, amount, transaction_id
        except sqlite3.Error as e:
            print(f"Error creating booking: {e}")
            return False

    def process_payment(self, booking_id, transaction_id):
        try:
            self.cursor.execute('''
            UPDATE payments 
            SET status = 'completed'
            WHERE booking_id = ? AND transaction_id = ?
            ''', (booking_id, transaction_id))

            self.cursor.execute('''
            UPDATE bookings 
            SET status = 'confirmed'
            WHERE booking_id = ?
            ''', (booking_id,))

            self.conn.commit()
            return True
        except sqlite3.Error as e:
            print(f"Error processing payment: {e}")
            return False

    def view_my_bookings(self):
        self.cursor.execute('''
        SELECT b.booking_id, c.court_name, b.booking_date, b.start_time, b.end_time,
               b.status, p.amount, p.status as payment_status
        FROM bookings b
        JOIN courts c ON b.court_id = c.court_id
        JOIN payments p ON b.booking_id = p.booking_id
        WHERE b.user_id = ?
        ORDER BY b.booking_date DESC, b.start_time DESC
        ''', (session['user_id'],))
        return self.cursor.fetchall()

    def cancel_booking(self, booking_id):
        try:
            self.cursor.execute('''
            UPDATE bookings 
            SET status = 'cancelled'
            WHERE booking_id = ? AND user_id = ?
            ''', (booking_id, session['user_id']))
            
            self.cursor.execute('''
            UPDATE payments 
            SET status = 'refunded'
            WHERE booking_id = ?
            ''', (booking_id,))

            self.conn.commit()
            return True
        except sqlite3.Error as e:
            print(f"Error cancelling booking: {e}")
            return False

# Initialize the booking system
booking_system = BadmintonBookingSystem()

@app.route('/')
def index():
    if 'user_id' in session:
        return redirect(url_for('dashboard'))
    return render_template('index.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        email = request.form['email']
        phone = request.form['phone']
        
        if booking_system.register_user(username, password, email, phone):
            flash('Registration successful! Please login.', 'success')
            return redirect(url_for('login'))
        else:
            flash('Registration failed. Username or email already exists.', 'error')
    
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        
        if booking_system.login(username, password):
            session['user_id'] = booking_system.current_user['user_id']
            session['username'] = booking_system.current_user['username']
            flash('Login successful!', 'success')
            return redirect(url_for('dashboard'))
        else:
            flash('Invalid credentials!', 'error')
    
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    flash('You have been logged out.', 'info')
    return redirect(url_for('index'))

@app.route('/dashboard')
def dashboard():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    bookings = booking_system.view_my_bookings()
    return render_template('dashboard.html', bookings=bookings)

@app.route('/courts', methods=['GET', 'POST'])
def view_courts():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    if request.method == 'POST':
        date = request.form['date']
        start_time = request.form['start_time']
        end_time = request.form['end_time']
        available_courts = booking_system.get_available_courts(date, start_time, end_time)
        return render_template('courts.html', courts=available_courts, 
                             selected_date=date, start_time=start_time, end_time=end_time)
    
    return render_template('courts.html', courts=None)

@app.route('/book', methods=['POST'])
def book_court():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    court_id = request.form['court_id']
    date = request.form['date']
    start_time = request.form['start_time']
    end_time = request.form['end_time']
    
    result = booking_system.create_booking(court_id, date, start_time, end_time)
    if result:
        booking_id, amount, transaction_id = result
        if booking_system.process_payment(booking_id, transaction_id):
            flash(f'Booking confirmed! Total amount: ${amount:.2f}', 'success')
        else:
            flash('Payment failed!', 'error')
    else:
        flash('Booking failed!', 'error')
    
    return redirect(url_for('dashboard'))

@app.route('/cancel/<int:booking_id>')
def cancel_booking(booking_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    if booking_system.cancel_booking(booking_id):
        flash('Booking cancelled successfully!', 'success')
    else:
        flash('Failed to cancel booking!', 'error')
    
    return redirect(url_for('dashboard'))

if __name__ == '__main__':
    app.run(debug=True)