"""
Script migrasi SATU KALI: memindahkan data user dari MySQL ke Firestore.

Jalankan ini SEKALI SAJA setelah app.py versi Firebase siap, supaya akun-akun
yang sudah ada (rizky/admin, budi/user, Komandan/atasan, dst) tetap bisa
dipakai login setelah aplikasi pindah ke Firestore.

Cara pakai:
    python migrate_users_to_firebase.py

Catatan: password hash yang lama TETAP DIPAKAI APA ADANYA (tidak diubah),
jadi semua user tetap bisa login pakai password mereka yang sekarang.
"""

import pymysql
import firebase_admin
from firebase_admin import credentials, firestore

# ==========================================
# KONFIGURASI - SESUAIKAN INI
# ==========================================
MYSQL_CONFIG = {
    'host': 'localhost',
    'user': 'root',
    'password': '',
    'database': 'portal_karyawan'
}

FIREBASE_CRED_FILENAME = 'portal-staf-32f99-firebase-adminsdk-fbsvc-3310b6857e.json'
# ==========================================

def main():
    print("Menghubungkan ke Firebase...")
    cred = credentials.Certificate(FIREBASE_CRED_FILENAME)
    firebase_admin.initialize_app(cred)
    fdb = firestore.client()

    print("Menghubungkan ke MySQL...")
    conn = pymysql.connect(**MYSQL_CONFIG, cursorclass=pymysql.cursors.DictCursor)

    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT id, fullname, email, password_hash, role, superior_id FROM user")
            users_mysql = cursor.fetchall()

        print(f"Ditemukan {len(users_mysql)} user di MySQL.")

        # Pemetaan id lama (integer MySQL) -> id baru (string Firestore)
        # Diperlukan supaya superior_id (yang menunjuk ke user lain) tetap benar.
        peta_id_lama_ke_baru = {}

        # Tahap 1: buat semua dokumen user dulu (tanpa superior_id dulu)
        for u in users_mysql:
            new_ref = fdb.collection('users').document()
            new_ref.set({
                'fullname': u['fullname'],
                'email': u['email'],
                'password_hash': u['password_hash'],
                'role': u['role'],
                'superior_id': None  # diisi di tahap 2
            })
            peta_id_lama_ke_baru[u['id']] = new_ref.id
            print(f"  - Dipindahkan: {u['fullname']} ({u['email']}) -> ID baru: {new_ref.id}")

        # Tahap 2: isi superior_id dengan ID Firestore yang benar
        for u in users_mysql:
            if u['superior_id']:
                id_baru = peta_id_lama_ke_baru.get(u['id'])
                id_atasan_baru = peta_id_lama_ke_baru.get(u['superior_id'])
                if id_baru and id_atasan_baru:
                    fdb.collection('users').document(id_baru).update({'superior_id': id_atasan_baru})
                    print(f"  - Menghubungkan {u['fullname']} ke atasannya.")

        print("\nSelesai! Semua user berhasil dipindahkan ke Firestore.")
        print("Silakan cek koleksi 'users' di Firebase Console untuk memastikan.")

    finally:
        conn.close()


if __name__ == '__main__':
    main()
