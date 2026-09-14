"""
Script migrasi SATU KALI: memindahkan data Pengumuman dan Jadwal Rapat
dari MySQL ke Firestore.

Jalankan ini SEKALI SAJA (opsional -- kalau memang masih ada data lama yang
mau dipertahankan) sebelum benar-benar meninggalkan XAMPP/MySQL.

Syarat: MySQL/XAMPP masih harus MENYALA saat menjalankan script ini
(karena perlu membaca data lama). Setelah migrasi selesai dan dicek,
XAMPP boleh dimatikan selamanya.

Cara pakai:
    pip install pymysql
    python migrate_pengumuman_jadwal_to_firebase.py
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
        # ===== Migrasi Pengumuman =====
        with conn.cursor() as cursor:
            cursor.execute("SELECT title, content, category, date FROM announcement")
            daftar_pengumuman = cursor.fetchall()

        print(f"Ditemukan {len(daftar_pengumuman)} pengumuman di MySQL.")
        for p in daftar_pengumuman:
            fdb.collection('pengumuman').document().set({
                'title': p['title'],
                'content': p['content'],
                'category': p['category'],
                'date': p['date']
            })
            print(f"  - Dipindahkan: {p['title']}")

        # ===== Migrasi Jadwal Rapat =====
        with conn.cursor() as cursor:
            cursor.execute("SELECT judul, tanggal, waktu, peserta FROM jadwal_rapat")
            daftar_rapat = cursor.fetchall()

        print(f"\nDitemukan {len(daftar_rapat)} jadwal rapat di MySQL.")
        for r in daftar_rapat:
            fdb.collection('jadwal_rapat').document().set({
                'judul': r['judul'],
                'tanggal': r['tanggal'].strftime('%Y-%m-%d'),
                'waktu': str(r['waktu']),
                'peserta': r['peserta']
            })
            print(f"  - Dipindahkan: {r['judul']}")

        print("\nSelesai! Semua data berhasil dipindahkan ke Firestore.")
        print("Silakan cek koleksi 'pengumuman' dan 'jadwal_rapat' di Firebase Console.")

    finally:
        conn.close()


if __name__ == '__main__':
    main()
