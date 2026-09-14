from flask import Flask, request, send_file, jsonify, render_template, session, redirect, url_for
from flask_cors import CORS
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash
from pdf2docx import Converter
from docx2pdf import convert

from functools import wraps
# Import tambahan untuk fitur ringkas dokumen
from docx import Document
from sumy.parsers.plaintext import PlaintextParser
from sumy.nlp.tokenizers import Tokenizer
from sumy.summarizers.lex_rank import LexRankSummarizer
# Import tambahan untuk meningkatkan akurasi Bahasa Indonesia
from Sastrawi.Stemmer.StemmerFactory import StemmerFactory
from Sastrawi.StopWordRemover.StopWordRemoverFactory import StopWordRemoverFactory
import datetime
import os
import base64
import requests

# ===================== TAMBAHAN: AUTO-DOWNLOAD DATA NLTK =====================
# Sumy (peringkasan dokumen & notulensi) butuh data tokenizer NLTK untuk
# memecah teks jadi kalimat. Blok ini otomatis mengunduh data tersebut kalau
# belum ada, supaya tidak perlu jalankan perintah manual tiap pindah komputer
# atau deploy ke server baru.
import nltk

def _pastikan_data_nltk_tersedia():
    paket_dibutuhkan = ['punkt_tab', 'punkt']
    for paket in paket_dibutuhkan:
        try:
            nltk.data.find(f'tokenizers/{paket}')
        except LookupError:
            print(f"[NLTK] Data '{paket}' belum ada, mengunduh otomatis...")
            try:
                nltk.download(paket, quiet=True)
                print(f"[NLTK] Berhasil mengunduh '{paket}'.")
            except Exception as e:
                print(f"[PERINGATAN] Gagal mengunduh data NLTK '{paket}': {e}")
                print("[PERINGATAN] Fitur Ringkas Dokumen & Notulensi Rapat mungkin tidak berfungsi.")

_pastikan_data_nltk_tersedia()
# ===============================================================================

# ===================== TAMBAHAN: NOTULENSI VIDEO RAPAT =====================
# Import untuk transkripsi audio/video rapat menjadi teks
import speech_recognition as sr
from pydub import AudioSegment
import math
import tempfile

# Path LANGSUNG ke ffmpeg.exe (Windows). Ini menghindari masalah PATH yang
# sering gagal. Kalau nanti pindah komputer atau deploy ke server Linux,
# ganti baris _FFMPEG_PATH ini sesuai lokasi ffmpeg di server tersebut
# (atau kosongkan jadi None agar otomatis pakai "ffmpeg" dari PATH sistem Linux).
_FFMPEG_PATH = r"C:\Users\MyBook Pro Max Army\Documents\OJT\ffmpeg-9.0.1-essentials_build\bin\ffmpeg.exe"
_FFMPEG_BIN_DIR = os.path.dirname(_FFMPEG_PATH)
_FFMPEG_READY = os.path.exists(_FFMPEG_PATH)

if _FFMPEG_READY:
    # PENTING: pydub juga butuh ffprobe.exe (file pendamping ffmpeg) untuk
    # membaca info durasi/format video. pydub mencari ffprobe lewat PATH
    # sistem, bukan lewat AudioSegment.converter. Supaya tidak perlu edit
    # System PATH Windows secara manual, kita tambahkan folder bin ini ke
    # PATH milik proses Python ini saja (tidak permanen, aman, tidak
    # mengubah pengaturan Windows Anda).
    os.environ["PATH"] = _FFMPEG_BIN_DIR + os.pathsep + os.environ.get("PATH", "")

    AudioSegment.converter = _FFMPEG_PATH
    _FFPROBE_PATH = os.path.join(_FFMPEG_BIN_DIR, 'ffprobe.exe')
    if os.path.exists(_FFPROBE_PATH):
        AudioSegment.ffprobe = _FFPROBE_PATH
        print(f"[OK] ffmpeg siap dipakai: {_FFMPEG_PATH}")
        print(f"[OK] ffprobe siap dipakai: {_FFPROBE_PATH}")
    else:
        print(f"[PERINGATAN] ffprobe.exe TIDAK ditemukan di folder: {_FFMPEG_BIN_DIR}")
        print("[PERINGATAN] Cek isi folder tersebut, harus ada ffmpeg.exe, ffplay.exe, DAN ffprobe.exe.")
else:
    print(f"[PERINGATAN] File ffmpeg TIDAK ditemukan di: {_FFMPEG_PATH}")
    print("[PERINGATAN] Cek kembali apakah path di atas sudah sesuai lokasi ffmpeg.exe Anda.")
    print("[PERINGATAN] Fitur Notulensi Rapat tidak akan berfungsi sampai ffmpeg tersedia.")
# =============================================================================


# Beri tahu Flask di mana folder template berada (yaitu, direktori saat ini, '.')
app = Flask(__name__, template_folder='.')
CORS(app) # Mengizinkan frontend mengambil data dari backend

# Kunci rahasia untuk mengamankan sesi. Ganti dengan string acak yang kuat.
app.secret_key = 'ganti-dengan-kunci-rahasia-yang-sangat-aman'

# ===================== TAMBAHAN: BATAS UKURAN UPLOAD =====================
# File video rapat bisa besar, default Flask tidak membatasi tapi server (mis. Werkzeug dev)
# bisa lambat/timeout untuk file sangat besar. Batas ini bisa disesuaikan (contoh: 500 MB).
app.config['MAX_CONTENT_LENGTH'] = 500 * 1024 * 1024
# ===========================================================================

# ===================== FIREBASE (SEKARANG SATU-SATUNYA DATABASE) =====================
# CATATAN: Migrasi ke Firebase SUDAH SELESAI TOTAL. MySQL/SQLAlchemy/XAMPP
# TIDAK LAGI DIPAKAI SAMA SEKALI oleh aplikasi ini. Semua data (User, Tugas,
# Pengumuman, Jadwal Rapat, Notulensi) sekarang tersimpan di Firestore.
#
# WAJIB: pip install firebase-admin
# WAJIB: taruh file kunci service account (.json) di folder project ini,
# lalu sesuaikan nama filenya di baris FIREBASE_CRED_FILENAME di bawah.
import firebase_admin
from firebase_admin import credentials, firestore

FIREBASE_CRED_FILENAME = 'portal-staf-32f99-firebase-adminsdk-fbsvc-128d85e3f3.json'
FIREBASE_CRED_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), FIREBASE_CRED_FILENAME)

try:
    cred = credentials.Certificate(FIREBASE_CRED_PATH)
    firebase_admin.initialize_app(cred)
    fdb = firestore.client()
    print(f"[OK] Firebase terhubung, memakai kunci: {FIREBASE_CRED_FILENAME}")
except Exception as e:
    fdb = None
    print(f"[PERINGATAN] Gagal menghubungkan Firebase: {e}")
    print(f"[PERINGATAN] Pastikan file '{FIREBASE_CRED_FILENAME}' ada di folder project ini.")
# =======================================================================================


# ===================== TELEGRAM BOT CONFIGURATION =====================
# Konfigurasi Telegram Bot untuk notifikasi
# Dapatkan BOT_TOKEN dari @BotFather di Telegram
# Chat ID user didapatkan setelah user memulai chat dengan bot
TELEGRAM_BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN', '8934991541:AAHGxS-qS8IRSgG_LaxwfBJKdQrWBQse3Ys')
TELEGRAM_API_URL = f'https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}'

def send_telegram_message(chat_id, text, parse_mode='HTML'):
    """Kirim pesan ke Telegram chat ID"""
    if not TELEGRAM_BOT_TOKEN or TELEGRAM_BOT_TOKEN == 'YOUR_BOT_TOKEN_HERE':
        print('[TELEGRAM] Bot token belum dikonfigurasi')
        return False
    
    try:
        url = f'{TELEGRAM_API_URL}/sendMessage'
        payload = {
            'chat_id': chat_id,
            'text': text,
            'parse_mode': parse_mode
        }
        response = requests.post(url, json=payload, timeout=10)
        if response.status_code == 200:
            print(f'[TELEGRAM] Pesan terkirim ke chat_id: {chat_id}')
            return True
        else:
            print(f'[TELEGRAM] Gagal kirim: {response.status_code} - {response.text}')
            return False
    except Exception as e:
        print(f'[TELEGRAM] Error: {e}')
        return False

def send_task_notification_telegram(user_data, task_data, assigned_by_name):
    """Kirim notifikasi tugas baru via Telegram"""
    if not user_data.get('telegram_chat_id'):
        return False
    
    priority_emoji = {'tinggi': '🔴', 'sedang': '🟡', 'rendah': '🟢'}.get(task_data.get('prioritas', 'sedang'), '🟡')
    
    deadline_text = ''
    if task_data.get('deadline'):
        try:
            deadline_dt = datetime.datetime.strptime(task_data['deadline'], '%Y-%m-%d')
            deadline_text = f'\n📅 <b>Deadline:</b> {deadline_dt.strftime("%d %B %Y")}'
        except:
            deadline_text = f'\n📅 <b>Deadline:</b> {task_data["deadline"]}'
    
    message = (
        f'📋 <b>TUGAS BARU DITUGASKAN</b>\n\n'
        f'📝 <b>Judul:</b> {task_data.get("judul", "-")}\n'
        f'📄 <b>Deskripsi:</b> {task_data.get("deskripsi", "-") or "-"}\n'
        f'{priority_emoji} <b>Prioritas:</b> {task_data.get("prioritas", "sedang").capitalize()}{deadline_text}\n'
        f'👤 <b>Diberikan oleh:</b> {assigned_by_name}\n'
        f'⏰ <b>Waktu:</b> {datetime.datetime.now().strftime("%d %B %Y %H:%M")}\n\n'
        f'Silakan buka aplikasi untuk melihat detail dan mengerjakan tugas.'
    )
    
    return send_telegram_message(user_data['telegram_chat_id'], message)


UPLOAD_FOLDER = 'uploads'
OUTPUT_FOLDER = 'outputs'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(OUTPUT_FOLDER, exist_ok=True)

# ===================== TAMBAHAN: FOLDER SEMENTARA UNTUK AUDIO =====================
TEMP_AUDIO_FOLDER = 'temp_audio'
os.makedirs(TEMP_AUDIO_FOLDER, exist_ok=True)
# Format video/audio yang diterima untuk fitur Notulensi Rapat
ALLOWED_MEDIA_EXTENSIONS = {'mp4', 'mov', 'avi', 'mkv', 'webm', 'mp3', 'wav', 'm4a', 'aac', 'ogg'}

def is_allowed_media(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_MEDIA_EXTENSIONS
# ====================================================================================

# ==========================================
# MODEL DATABASE (Cetak Biru Tabel)
# ==========================================
# CATATAN: SEMUA model (User, Tugas, JadwalRapat, Announcement, Notulensi)
# SUDAH DIPINDAH ke Firestore. Tidak ada lagi model SQLAlchemy/MySQL yang
# dipakai di aplikasi ini. XAMPP/MySQL sudah bisa ditinggalkan sepenuhnya.


# ==========================================
# DECORATORS UNTUK KEAMANAN
# ==========================================
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            # Jika ini adalah permintaan API, kirim error JSON. Jika tidak, alihkan.
            if request.path.startswith('/api/'):
                return jsonify(error="Sesi telah berakhir, silakan login kembali."), 401
            return redirect(url_for('serve_login_page'))
        return f(*args, **kwargs)
    return decorated_function

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            if request.path.startswith('/api/'):
                return jsonify(error="Sesi telah berakhir, silakan login kembali."), 401
            return redirect(url_for('serve_login_page'))
        if session.get('user_role') != 'admin':
            if request.path.startswith('/api/'):
                return jsonify(error="Akses admin diperlukan."), 403
            return "Akses Ditolak", 403
        return f(*args, **kwargs)
    return decorated_function

# ===================== TAMBAHAN: DECORATOR ATASAN =====================
def atasan_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            if request.path.startswith('/api/'):
                return jsonify(error="Sesi telah berakhir, silakan login kembali."), 401
            return redirect(url_for('serve_login_page'))
        if session.get('user_role') not in ('atasan', 'admin'):
            if request.path.startswith('/api/'):
                return jsonify(error="Akses atasan diperlukan."), 403
            return "Akses Ditolak", 403
        return f(*args, **kwargs)
    return decorated_function
# =========================================================================

# API 1: Konversi PDF ke Word
@app.route('/api/pdf-to-word', methods=['POST'])
def pdf_to_word():
    if 'file' not in request.files:
        return jsonify({"error": "Tidak ada file"}), 400
    
    file = request.files['file']
    filename = secure_filename(file.filename)
    input_path = os.path.join(UPLOAD_FOLDER, filename)
    output_filename = filename.rsplit('.', 1)[0] + '.docx'
    output_path = os.path.join(OUTPUT_FOLDER, output_filename)
    
    file.save(input_path)

    try:
        # Menggunakan engine pdf2docx untuk konversi akurat
        cv = Converter(input_path)
        cv.convert(output_path, start=0, end=None)
        cv.close()
        return send_file(output_path, as_attachment=True)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# API 2: Konversi Word ke PDF
@app.route('/api/word-to-pdf', methods=['POST'])
def word_to_pdf():
    if 'file' not in request.files:
        return jsonify({"error": "Tidak ada file"}), 400
    
    file = request.files['file']
    filename = secure_filename(file.filename)
    input_path = os.path.join(UPLOAD_FOLDER, filename)
    output_filename = filename.rsplit('.', 1)[0] + '.pdf'
    output_path = os.path.join(OUTPUT_FOLDER, output_filename)
    
    file.save(input_path)

    try:
        # Membutuhkan MS Word terinstal di OS server (Windows/Mac)
        convert(input_path, output_path)
        return send_file(output_path, as_attachment=True)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ===================== TAMBAHAN: FUNGSI RINGKASAN DIPAKAI ULANG =====================
# Fungsi ini diambil dari logika /api/summarize agar bisa dipakai ulang
# oleh fitur Notulensi Rapat (meringkas hasil transkrip suara).
def generate_summary_from_text(text_content, rasio_ringkasan=0.35, min_kalimat=2, maks_kalimat=10):
    if not text_content or not text_content.strip():
        return "Teks tidak berisi konten untuk diringkas."

    # CATATAN: NLTK tidak menyediakan model tokenizer kalimat untuk Bahasa
    # Indonesia (punkt_tab hanya mendukung beberapa bahasa seperti Inggris,
    # Jerman, Prancis, dll). Kita pakai tokenizer Inggris untuk memisah
    # kalimat (aturan tanda baca cukup mirip), sementara pemahaman kata
    # Bahasa Indonesia tetap ditangani oleh stemmer & stopword Sastrawi.
    parser = PlaintextParser.from_string(text_content, Tokenizer("english"))

    total_kalimat = len(list(parser.document.sentences))

    # Kalau teks aslinya memang sudah pendek (sedikit kalimat), tidak ada
    # gunanya "meringkas" lebih jauh lagi -- kembalikan apa adanya saja
    # daripada memaksakan hasil yang terlihat identik dengan aslinya.
    if total_kalimat <= min_kalimat:
        return text_content.strip()

    stemmer_factory = StemmerFactory()
    stemmer = stemmer_factory.create_stemmer()

    summarizer = LexRankSummarizer(stemmer.stem)

    stopword_factory = StopWordRemoverFactory()
    summarizer.stop_words = stopword_factory.get_stop_words()

    # Jumlah kalimat ringkasan menyesuaikan panjang teks asli (proporsional),
    # dibatasi antara min_kalimat dan maks_kalimat.
    jumlah_kalimat = max(min_kalimat, min(maks_kalimat, round(total_kalimat * rasio_ringkasan)))

    summary_sentences = summarizer(parser.document, jumlah_kalimat)

    if not summary_sentences:
        return "Gagal membuat ringkasan. Teks mungkin terlalu pendek atau kurang bervariasi."

    return '\n\n'.join([str(sentence) for sentence in summary_sentences])
# ======================================================================================


# API 3: Ringkas Dokumen (dari file .docx)
@app.route('/api/summarize', methods=['POST'])
def summarize_document():
    if 'file' not in request.files:
        return jsonify({"error": "Tidak ada file yang diunggah"}), 400

    file = request.files['file']
    if file.filename == '':
        return jsonify({"error": "Tidak ada file yang dipilih"}), 400

    filename = secure_filename(file.filename)
    input_path = os.path.join(UPLOAD_FOLDER, filename)
    file.save(input_path)

    try:
        # 1. Ekstrak teks dari file .docx
        doc = Document(input_path)
        full_text = [para.text for para in doc.paragraphs if para.text.strip() != '']
        text_content = '\n'.join(full_text)

        if not text_content:
            return jsonify({"summary": "Dokumen tidak berisi teks untuk diringkas."})

        # 2. Lakukan peringkasan menggunakan fungsi bersama (lihat generate_summary_from_text)
        summary = generate_summary_from_text(text_content)

        return jsonify({"summary": summary})
    except Exception as e:
        return jsonify({"error": f"Gagal memproses dokumen: {str(e)}"}), 500


# ===================== TAMBAHAN: FITUR NOTULENSI VIDEO RAPAT =====================

def _extract_audio_to_wav(input_path, wav_path):
    """Mengekstrak/mengonversi file video/audio apa pun menjadi WAV mono 16kHz
    agar bisa diproses oleh SpeechRecognition. Membutuhkan ffmpeg terpasang
    dan tersedia di PATH sistem."""
    audio = AudioSegment.from_file(input_path)
    audio = audio.set_channels(1).set_frame_rate(16000)
    audio.export(wav_path, format='wav')
    return audio.duration_seconds


def _transcribe_wav(wav_path, durasi_detik, bahasa='id-ID', panjang_chunk_detik=20):
    """Memecah audio panjang menjadi beberapa potongan (chunk) lalu mengirim
    tiap potongan ke Google Web Speech API untuk ditranskripsi. Membutuhkan
    koneksi internet aktif di server."""
    recognizer = sr.Recognizer()
    hasil_teks = []

    jumlah_chunk = max(1, math.ceil(durasi_detik / panjang_chunk_detik))
    audio_full = AudioSegment.from_wav(wav_path)

    for i in range(jumlah_chunk):
        start_ms = int(i * panjang_chunk_detik * 1000)
        end_ms = int(min((i + 1) * panjang_chunk_detik * 1000, durasi_detik * 1000))
        chunk = audio_full[start_ms:end_ms]

        with tempfile.NamedTemporaryFile(suffix='.wav', delete=False, dir=TEMP_AUDIO_FOLDER) as tmp_chunk:
            chunk_path = tmp_chunk.name
        chunk.export(chunk_path, format='wav')

        try:
            with sr.AudioFile(chunk_path) as source:
                audio_data = recognizer.record(source)
            teks_chunk = recognizer.recognize_google(audio_data, language=bahasa)
            # PENTING: Google Speech API mengembalikan teks TANPA tanda baca sama
            # sekali. Kalau tidak diberi tanda titik di sini, seluruh transkrip
            # akan dianggap 1 kalimat raksasa oleh sistem peringkas (sumy),
            # sehingga hasil "ringkasan" jadi sama saja dengan teks aslinya.
            # Kita tandai batas tiap potongan audio sebagai batas kalimat.
            if teks_chunk:
                hasil_teks.append(teks_chunk.strip() + '.')
        except sr.UnknownValueError:
            hasil_teks.append('[bagian ini tidak terdengar jelas].')
        except sr.RequestError as e:
            hasil_teks.append(f'[gagal menghubungi layanan transkripsi: {e}].')
        finally:
            if os.path.exists(chunk_path):
                os.remove(chunk_path)

    return ' '.join(hasil_teks).strip()


@app.route('/api/notulensi', methods=['POST'])
@login_required
def buat_notulensi():
    if not _FFMPEG_READY:
        return jsonify({"error": f"ffmpeg belum siap di server. Path yang dicek: {_FFMPEG_PATH}. Pastikan file ffmpeg.exe benar-benar ada di path tersebut, lalu restart server."}), 500

    if 'file' not in request.files:
        return jsonify({"error": "Tidak ada file video/audio yang diunggah."}), 400

    file = request.files['file']
    judul = request.form.get('judul', '').strip()
    peserta = request.form.get('peserta', '').strip()

    if file.filename == '' or not judul:
        return jsonify({"error": "Judul rapat dan file wajib diisi."}), 400

    if not is_allowed_media(file.filename):
        return jsonify({"error": "Format file tidak didukung. Gunakan mp4, mov, mkv, mp3, wav, m4a, dll."}), 400

    filename = secure_filename(file.filename)
    input_path = os.path.join(UPLOAD_FOLDER, filename)
    file.save(input_path)

    wav_path = os.path.join(TEMP_AUDIO_FOLDER, filename.rsplit('.', 1)[0] + '_convert.wav')

    try:
        # 1. Ekstrak audio dari video/audio menjadi WAV
        durasi_detik = _extract_audio_to_wav(input_path, wav_path)

        # 2. Transkripsi audio menjadi teks
        transkrip = _transcribe_wav(wav_path, durasi_detik)

        if not transkrip:
            return jsonify({"error": "Tidak ada suara yang berhasil dikenali dari file ini."}), 422

        # 3. Ringkas transkrip menjadi poin-poin notulensi
        ringkasan = generate_summary_from_text(transkrip)

        # 4. Simpan ke Firestore
        new_ref = fdb.collection('notulensi').document()
        new_ref.set({
            'judul': judul,
            'peserta': peserta,
            'transkrip': transkrip,
            'ringkasan': ringkasan,
            'durasi_detik': int(durasi_detik),
            'tanggal': datetime.datetime.now().strftime('%d %b %Y %H:%M'),
            'dibuat_oleh': session.get('user_name', 'Tidak diketahui')
        })

        return jsonify({
            "message": "Notulensi berhasil dibuat!",
            "id": new_ref.id,
            "transkrip": transkrip,
            "ringkasan": ringkasan,
            "durasi_detik": int(durasi_detik)
        }), 201

    except FileNotFoundError as e:
        # Biasanya terjadi jika ffmpeg tidak ditemukan atau file rusak
        return jsonify({"error": f"Gagal memproses media (ffmpeg tidak ditemukan): {str(e)}. Cek kembali path ffmpeg.exe di app.py sudah benar, lalu restart server."}), 500
    except Exception as e:
        return jsonify({"error": f"Gagal membuat notulensi: {str(e)}"}), 500
    finally:
        # Bersihkan file sementara
        if os.path.exists(input_path):
            os.remove(input_path)
        if os.path.exists(wav_path):
            os.remove(wav_path)


@app.route('/api/notulensi', methods=['GET'])
@login_required
def get_notulensi_list():
    docs = fdb.collection('notulensi').stream()
    hasil = []
    for d in docs:
        n = d.to_dict()
        hasil.append({
            'id': d.id,
            'judul': n.get('judul'),
            'peserta': n.get('peserta'),
            'ringkasan': n.get('ringkasan'),
            'durasi_detik': n.get('durasi_detik'),
            'tanggal': n.get('tanggal'),
            'dibuat_oleh': n.get('dibuat_oleh')
        })
    # Urutkan terbaru dulu (berdasarkan tanggal string 'dd Mon YYYY HH:MM' tidak selalu urut leksikografis,
    # jadi kita pakai ID dokumen terbalik sebagai pendekatan sederhana kalau tidak ada field waktu tambahan)
    hasil.reverse()
    return jsonify(hasil)


@app.route('/api/notulensi/<string:notulensi_id>', methods=['GET'])
@login_required
def get_notulensi_detail(notulensi_id):
    doc = fdb.collection('notulensi').document(notulensi_id).get()
    if not doc.exists:
        return jsonify({"error": "Notulensi tidak ditemukan."}), 404
    n = doc.to_dict()
    return jsonify({
        'id': doc.id,
        'judul': n.get('judul'),
        'peserta': n.get('peserta'),
        'transkrip': n.get('transkrip'),
        'ringkasan': n.get('ringkasan'),
        'durasi_detik': n.get('durasi_detik'),
        'tanggal': n.get('tanggal'),
        'dibuat_oleh': n.get('dibuat_oleh')
    })


@app.route('/api/notulensi/<string:notulensi_id>', methods=['DELETE'])
@login_required
def delete_notulensi(notulensi_id):
    doc_ref = fdb.collection('notulensi').document(notulensi_id)
    if not doc_ref.get().exists:
        return jsonify({"error": "Notulensi tidak ditemukan."}), 404
    try:
        doc_ref.delete()
        return jsonify({"message": "Notulensi berhasil dihapus."}), 200
    except Exception as e:
        return jsonify({"error": f"Gagal menghapus notulensi: {str(e)}"}), 500


@app.route('/USER/notulensi-rapat.html')
@login_required
def serve_user_notulensi():
    return render_template('USER/notulensi-rapat.html', user_name=session.get('user_name', 'Pengguna'))

# ====================================================================================


# ===================== TAMBAHAN: FITUR TUGAS SAYA (FIRESTORE - TAHAP 1) =====================
# Koleksi Firestore: 'tugas'. ID dokumen berupa string (bukan angka lagi).

def _serialize_tugas(doc, sertakan_nama_pemberi=False, sertakan_nama_penerima=False):
    t = doc.to_dict()
    hasil = {
        'id': doc.id,
        'judul': t.get('judul'),
        'deskripsi': t.get('deskripsi'),
        'prioritas': t.get('prioritas', 'sedang'),
        'status': t.get('status', 'belum'),
        'user_id': t.get('user_id'),
        'assigned_by': t.get('assigned_by'),
        'deadline': t.get('deadline'),
        'deadline_tampil': None,
        'bisa_diedit': t.get('assigned_by') is None,
        'bisa_dihapus': t.get('assigned_by') is None
    }
    if t.get('deadline'):
        try:
            hasil['deadline_tampil'] = datetime.datetime.strptime(t.get('deadline'), '%Y-%m-%d').strftime('%d %b %Y')
        except Exception:
            hasil['deadline_tampil'] = t.get('deadline')

    if sertakan_nama_pemberi and t.get('assigned_by'):
        pemberi_doc = fdb.collection('users').document(t.get('assigned_by')).get()
        hasil['diberikan_oleh'] = pemberi_doc.to_dict().get('fullname') if pemberi_doc.exists else None
    if sertakan_nama_penerima and t.get('user_id'):
        penerima_doc = fdb.collection('users').document(t.get('user_id')).get()
        hasil['diberikan_kepada'] = penerima_doc.to_dict().get('fullname') if penerima_doc.exists else 'Tidak diketahui'
        hasil['diberikan_kepada_id'] = t.get('user_id')
    return hasil


@app.route('/api/tugas', methods=['GET'])
@login_required
def get_tugas_list():
    user_id = session.get('user_id')
    status_filter = request.args.get('status', 'semua')

    query = fdb.collection('tugas').where('user_id', '==', user_id)
    docs = list(query.stream())

    hasil = [_serialize_tugas(d, sertakan_nama_pemberi=True) for d in docs]

    if status_filter and status_filter != 'semua':
        hasil = [h for h in hasil if h['status'] == status_filter]

    # Urutkan di Python: status lalu deadline (hindari perlu composite index Firestore)
    hasil.sort(key=lambda h: (h['status'], h['deadline'] or '9999-99-99'))
    return jsonify(hasil)


@app.route('/api/tugas', methods=['POST'])
@login_required
def add_tugas():
    data = request.get_json(silent=True) or request.form

    judul = (data.get('judul') or '').strip()
    deskripsi = (data.get('deskripsi') or '').strip()
    prioritas = data.get('prioritas', 'sedang')
    deadline_str = data.get('deadline')

    if not judul:
        return jsonify({"error": "Judul tugas wajib diisi."}), 400
    if prioritas not in ('rendah', 'sedang', 'tinggi'):
        prioritas = 'sedang'
    if deadline_str:
        try:
            datetime.datetime.strptime(deadline_str, '%Y-%m-%d')
        except ValueError:
            return jsonify({"error": "Format tanggal deadline tidak valid."}), 400

    try:
        new_ref = fdb.collection('tugas').document()
        new_ref.set({
            'user_id': session.get('user_id'),
            'assigned_by': None,
            'judul': judul,
            'deskripsi': deskripsi,
            'prioritas': prioritas,
            'status': 'belum',
            'deadline': deadline_str or None,
            'dibuat_pada': firestore.SERVER_TIMESTAMP
        })
        return jsonify({"message": "Tugas berhasil ditambahkan.", "id": new_ref.id}), 201
    except Exception as e:
        return jsonify({"error": f"Gagal menambahkan tugas: {str(e)}"}), 500


@app.route('/api/tugas/<string:tugas_id>', methods=['PUT'])
@login_required
def update_tugas(tugas_id):
    tugas_ref = fdb.collection('tugas').document(tugas_id)
    tugas_doc = tugas_ref.get()
    if not tugas_doc.exists:
        return jsonify({"error": "Tugas tidak ditemukan."}), 404

    tugas = tugas_doc.to_dict()
    if tugas.get('user_id') != session.get('user_id'):
        return jsonify({"error": "Anda tidak memiliki akses ke tugas ini."}), 403

    data = request.get_json(silent=True) or request.form
    hanya_boleh_ubah_status = tugas.get('assigned_by') is not None

    try:
        update_data = {}
        if not hanya_boleh_ubah_status:
            if 'judul' in data and data.get('judul', '').strip():
                update_data['judul'] = data.get('judul').strip()
            if 'deskripsi' in data:
                update_data['deskripsi'] = data.get('deskripsi', '').strip()
            if 'prioritas' in data and data.get('prioritas') in ('rendah', 'sedang', 'tinggi'):
                update_data['prioritas'] = data.get('prioritas')
            if 'deadline' in data:
                update_data['deadline'] = data.get('deadline') or None

        if 'status' in data and data.get('status') in ('belum', 'proses', 'selesai'):
            update_data['status'] = data.get('status')

        if update_data:
            tugas_ref.update(update_data)
        return jsonify({"message": "Tugas berhasil diperbarui."}), 200
    except Exception as e:
        return jsonify({"error": f"Gagal memperbarui tugas: {str(e)}"}), 500


@app.route('/api/tugas/<string:tugas_id>', methods=['DELETE'])
@login_required
def delete_tugas(tugas_id):
    tugas_ref = fdb.collection('tugas').document(tugas_id)
    tugas_doc = tugas_ref.get()
    if not tugas_doc.exists:
        return jsonify({"error": "Tugas tidak ditemukan."}), 404

    tugas = tugas_doc.to_dict()
    if tugas.get('user_id') != session.get('user_id'):
        return jsonify({"error": "Anda tidak memiliki akses ke tugas ini."}), 403
    if tugas.get('assigned_by') is not None:
        return jsonify({"error": "Tugas ini diberikan oleh atasan, hanya atasan yang bisa menghapusnya."}), 403

    try:
        tugas_ref.delete()
        return jsonify({"message": "Tugas berhasil dihapus."}), 200
    except Exception as e:
        return jsonify({"error": f"Gagal menghapus tugas: {str(e)}"}), 500


@app.route('/USER/tugas-saya.html')
@login_required
def serve_user_tugas():
    return render_template('USER/tugas-saya.html', user_name=session.get('user_name', 'Pengguna'), user_id=session.get('user_id'))

# ===============================================================================================


# ===================== TAMBAHAN: ATASAN MEMBERI TUGAS KE STAF (FIRESTORE) =====================

@app.route('/api/atasan/staf', methods=['GET'])
@atasan_required
def get_staf_tim():
    atasan_id = session.get('user_id')
    try:
        if session.get('user_role') == 'admin':
            docs = fdb.collection('users').where('role', '==', 'user').stream()
        else:
            docs = fdb.collection('users').where('superior_id', '==', atasan_id).stream()
        return jsonify([{'id': d.id, 'fullname': d.to_dict().get('fullname'), 'email': d.to_dict().get('email')} for d in docs])
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/atasan/tugas', methods=['GET'])
@atasan_required
def get_tugas_yang_diberikan():
    atasan_id = session.get('user_id')
    try:
        docs = list(fdb.collection('tugas').where('assigned_by', '==', atasan_id).stream())
        hasil = [_serialize_tugas(d, sertakan_nama_penerima=True) for d in docs]
        hasil.sort(key=lambda h: h['status'])
        return jsonify(hasil)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/atasan/tugas', methods=['POST'])
@atasan_required
def beri_tugas():
    data = request.get_json(silent=True) or request.form

    target_user_id = data.get('user_id')
    judul = (data.get('judul') or '').strip()
    deskripsi = (data.get('deskripsi') or '').strip()
    prioritas = data.get('prioritas', 'sedang')
    deadline_str = data.get('deadline')

    if not target_user_id or not judul:
        return jsonify({"error": "Staf tujuan dan judul tugas wajib diisi."}), 400

    target_doc = fdb.collection('users').document(target_user_id).get()
    if not target_doc.exists:
        return jsonify({"error": "Staf tujuan tidak ditemukan."}), 404
    target_user = target_doc.to_dict()

    if session.get('user_role') == 'atasan' and target_user.get('superior_id') != session.get('user_id'):
        return jsonify({"error": "Anda hanya bisa memberi tugas ke staf di tim Anda sendiri."}), 403

    if prioritas not in ('rendah', 'sedang', 'tinggi'):
        prioritas = 'sedang'
    if deadline_str:
        try:
            datetime.datetime.strptime(deadline_str, '%Y-%m-%d')
        except ValueError:
            return jsonify({"error": "Format tanggal deadline tidak valid."}), 400

    try:
        new_task_ref = fdb.collection('tugas').document()
        new_task_ref.set({
            'user_id': target_user_id,
            'assigned_by': session.get('user_id'),
            'judul': judul,
            'deskripsi': deskripsi,
            'prioritas': prioritas,
            'status': 'belum',
            'deadline': deadline_str or None,
            'dibuat_pada': firestore.SERVER_TIMESTAMP
        })
        
        # Kirim notifikasi Telegram ke staf yang mendapat tugas
        assigned_by_doc = fdb.collection('users').document(session.get('user_id')).get()
        assigned_by_name = assigned_by_doc.to_dict().get('fullname', 'Atasan') if assigned_by_doc.exists else 'Atasan'
        
        task_data = {
            'judul': judul,
            'deskripsi': deskripsi,
            'prioritas': prioritas,
            'deadline': deadline_str
        }
        
        # Debug: check if target_user has telegram_chat_id
        chat_id = target_user.get('telegram_chat_id')
        print(f'[TELEGRAM DEBUG] Target user: {target_user.get("fullname")}, chat_id: {chat_id}')
        
        if chat_id:
            send_task_notification_telegram(target_user, task_data, assigned_by_name)
        else:
            print('[TELEGRAM] Target user belum menghubungkan akun Telegram')
        
        return jsonify({"message": f"Tugas berhasil diberikan ke {target_user.get('fullname')}."}), 201
    except Exception as e:
        return jsonify({"error": f"Gagal memberi tugas: {str(e)}"}), 500


@app.route('/api/atasan/tugas/<string:tugas_id>', methods=['DELETE'])
@atasan_required
def batalkan_tugas(tugas_id):
    tugas_ref = fdb.collection('tugas').document(tugas_id)
    tugas_doc = tugas_ref.get()
    if not tugas_doc.exists:
        return jsonify({"error": "Tugas tidak ditemukan."}), 404

    tugas = tugas_doc.to_dict()
    if session.get('user_role') != 'admin' and tugas.get('assigned_by') != session.get('user_id'):
        return jsonify({"error": "Anda tidak memiliki akses ke tugas ini."}), 403

    try:
        tugas_ref.delete()
        return jsonify({"message": "Tugas berhasil dibatalkan."}), 200
    except Exception as e:
        return jsonify({"error": f"Gagal membatalkan tugas: {str(e)}"}), 500


@app.route('/atasan/beri-tugas.html')
@login_required
def serve_atasan_beri_tugas():
    if session.get('user_role') != 'atasan':
        return "Akses Ditolak", 403
    return render_template('atasan/beri-tugas.html', user_name=session.get('user_name', 'Atasan'), user_id=session.get('user_id'))


# ===================== TAMBAHAN: KONFIGURASI FIREBASE UNTUK FRONTEND =====================
# Endpoint ini mengirim firebaseConfig (yang memang aman untuk publik) ke
# halaman frontend, supaya JS bisa connect langsung ke Firestore untuk
# fitur real-time (tanpa hardcode config di tiap file HTML).
@app.route('/api/firebase-config', methods=['GET'])
@login_required
def get_firebase_config():
    return jsonify({
        "apiKey": "AIzaSyCvpvS1pcR62YC5EDswvT7RhdZNDfflL74",
        "authDomain": "portal-staf-32f99.firebaseapp.com",
        "projectId": "portal-staf-32f99",
        "storageBucket": "portal-staf-32f99.firebasestorage.app",
        "messagingSenderId": "272016722988",
        "appId": "1:272016722988:web:bc04a4617dcdb7e9109589"
    })

# =============================================================================================





# ==========================================
# API UNTUK OTENTIKASI PENGGUNA
# ==========================================

@app.route('/login', methods=['POST'])
def handle_login():
    email = request.form.get('email')
    password = request.form.get('password')

    # ===== FIRESTORE (Tahap 1) =====
    users_query = fdb.collection('users').where('email', '==', email).limit(1).stream()
    user_doc = next(users_query, None)

    if user_doc and check_password_hash(user_doc.to_dict().get('password_hash', ''), password):
        user = user_doc.to_dict()
        session['user_id'] = user_doc.id
        session['user_name'] = user.get('fullname')
        session['user_email'] = user.get('email')
        session['user_role'] = user.get('role')

        role = user.get('role')
        if role == 'admin':
            redirect_url = url_for('serve_admin_dashboard')
        elif role == 'atasan':
            redirect_url = url_for('serve_atasan_dashboard')
        else:  # 'user'
            redirect_url = url_for('serve_user_dashboard')

        return jsonify({"message": "Login berhasil!", "redirect_url": redirect_url})

    return jsonify({"error": "Email atau kata sandi salah"}), 401

@app.route('/register', methods=['POST'])
def handle_register():
    fullname = request.form.get('fullname')
    email = request.form.get('email')
    password = request.form.get('password')

    if not all([fullname, email, password]):
        return jsonify({"error": "Semua kolom harus diisi."}), 400

    # ===== FIRESTORE (Tahap 1) =====
    existing = list(fdb.collection('users').where('email', '==', email).limit(1).stream())
    if existing:
        return jsonify({"error": "Email sudah terdaftar."}), 409

    hashed_password = generate_password_hash(password)
    fdb.collection('users').document().set({
        'fullname': fullname,
        'email': email,
        'password_hash': hashed_password,
        'role': 'user',
        'superior_id': None
    })

    return jsonify({"message": "Registrasi berhasil! Anda akan diarahkan ke halaman login.", "redirect_url": url_for('serve_login_page')})

@app.route('/api/users', methods=['GET'])
@admin_required
def get_users():
    try:
        docs = fdb.collection('users').stream()
        users_list = []
        for doc in docs:
            u = doc.to_dict()
            users_list.append({
                'id': doc.id,
                'fullname': u.get('fullname'),
                'email': u.get('email'),
                'role': u.get('role'),
                'superior_id': u.get('superior_id')
            })
        return jsonify(users_list)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/superiors', methods=['GET'])
@admin_required
def get_superiors():
    try:
        docs = fdb.collection('users').where('role', '==', 'atasan').stream()
        return jsonify([{'id': d.id, 'fullname': d.to_dict().get('fullname')} for d in docs])
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/user/profile', methods=['GET'])
@login_required
def get_user_profile():
    user_id = session.get('user_id')
    user_ref = fdb.collection('users').document(user_id)
    user_doc = user_ref.get()
    if not user_doc.exists:
        return jsonify({"error": "Pengguna tidak ditemukan."}), 404
    user = user_doc.to_dict()
    return jsonify({
        'nama': user.get('fullname', ''),
        'nrp': user.get('nrp', ''),
        'asal': user.get('asal', ''),
        'gender': user.get('gender', ''),
        'email': user.get('email', ''),
        'telepon': user.get('telepon', ''),
        'foto': user.get('foto', ''),
        'telegram_chat_id': user.get('telegram_chat_id', '')
    }), 200


@app.route('/api/user/profile', methods=['POST'])
@login_required
def update_user_profile():
    user_id = session.get('user_id')
    user_ref = fdb.collection('users').document(user_id)
    user_doc = user_ref.get()
    if not user_doc.exists:
        return jsonify({"error": "Pengguna tidak ditemukan."}), 404

    try:
        # Handle form data (including file upload)
        if request.content_type and request.content_type.startswith('multipart/form-data'):
            nama = request.form.get('nama', '').strip()
            nrp = request.form.get('nrp', '').strip()
            asal = request.form.get('asal', '').strip()
            gender = request.form.get('gender', '').strip()
            email = request.form.get('email', '').strip()
            telepon = request.form.get('telepon', '').strip()
            
            update_data = {}
            if nama: update_data['fullname'] = nama
            if nrp: update_data['nrp'] = nrp
            if asal: update_data['asal'] = asal
            if gender: update_data['gender'] = gender
            if email: update_data['email'] = email
            if telepon: update_data['telepon'] = telepon
            
            # Handle photo upload
            if 'foto' in request.files:
                file = request.files['foto']
                if file and file.filename:
                    # Convert to base64 for storage in Firestore
                    import base64
                    file_data = file.read()
                    file_b64 = base64.b64encode(file_data).decode('utf-8')
                    mime_type = file.content_type or 'image/jpeg'
                    update_data['foto'] = f'data:{mime_type};base64,{file_b64}'
            
            if update_data:
                user_ref.update(update_data)
                # Update session name if changed
                if nama:
                    session['user_name'] = nama
                return jsonify({"message": "Profil berhasil diperbarui."}), 200
            else:
                return jsonify({"error": "Tidak ada data yang diubah."}), 400
        else:
            return jsonify({"error": "Content-Type harus multipart/form-data"}), 400
            
    except Exception as e:
        return jsonify({"error": f"Gagal memperbarui profil: {str(e)}"}), 500


@app.route('/api/change-password', methods=['POST'])
@login_required
def change_password():
    user_id = session.get('user_id')
    old_password = request.form.get('old_password')
    new_password = request.form.get('new_password')
    confirm_new_password = request.form.get('confirm_new_password')

    if not all([old_password, new_password, confirm_new_password]):
        return jsonify({"error": "Semua kolom harus diisi."}), 400

    if new_password != confirm_new_password:
        return jsonify({"error": "Kata sandi baru dan konfirmasi tidak cocok."}), 400

    if len(new_password) < 6:
        return jsonify({"error": "Kata sandi baru minimal 6 karakter."}), 400

    user_ref = fdb.collection('users').document(user_id)
    user_doc = user_ref.get()
    if not user_doc.exists:
        session.clear()
        return jsonify({"error": "Pengguna tidak ditemukan."}), 401

    user = user_doc.to_dict()
    if not check_password_hash(user.get('password_hash', ''), old_password):
        return jsonify({"error": "Kata sandi lama salah."}), 401

    user_ref.update({'password_hash': generate_password_hash(new_password)})

    return jsonify({"message": "Kata sandi berhasil diubah."}), 200


# ===================== TELEGRAM LINK/UNLINK ENDPOINTS =====================
@app.route('/api/user/telegram/link', methods=['POST'])
@login_required
def link_telegram():
    """Link user's Telegram account by providing chat_id"""
    user_id = session.get('user_id')
    data = request.get_json(silent=True) or request.form
    chat_id = data.get('chat_id', '').strip()
    
    if not chat_id:
        return jsonify({"error": "Chat ID Telegram wajib diisi."}), 400
    
    # Validate chat_id format (numeric or @username)
    if not (chat_id.startswith('@') or chat_id.lstrip('-').isdigit()):
        return jsonify({"error": "Format Chat ID tidak valid. Gunakan ID numerik atau @username."}), 400
    
    user_ref = fdb.collection('users').document(user_id)
    user_ref.update({'telegram_chat_id': chat_id})
    
    # Send test message
    test_sent = send_telegram_message(chat_id, '✅ <b>Akun Telegram berhasil terhubung!</b>\n\nAnda akan menerima notifikasi tugas baru melalui bot ini.')
    
    if test_sent:
        return jsonify({"message": "Telegram berhasil ditautkan dan pesan tes terkirim."}), 200
    else:
        # Still save but warn
        return jsonify({"message": "Telegram ditautkan, tapi pesan tes gagal. Pastikan bot sudah di-start dan Chat ID benar."}), 200


@app.route('/api/user/telegram/unlink', methods=['POST'])
@login_required
def unlink_telegram():
    """Unlink user's Telegram account"""
    user_id = session.get('user_id')
    user_ref = fdb.collection('users').document(user_id)
    user_ref.update({'telegram_chat_id': firestore.DELETE_FIELD})
    
    return jsonify({"message": "Telegram berhasil dilepaskan."}), 200


@app.route('/api/user/telegram/status', methods=['GET'])
@login_required
def telegram_status():
    """Check if user has Telegram linked"""
    user_id = session.get('user_id')
    user_doc = fdb.collection('users').document(user_id).get()
    if not user_doc.exists:
        return jsonify({"error": "Pengguna tidak ditemukan."}), 404
    
    user = user_doc.to_dict()
    return jsonify({
        "linked": bool(user.get('telegram_chat_id')),
        "chat_id": user.get('telegram_chat_id', '')
    }), 200


@app.route('/api/user/delete/<string:user_id>', methods=['DELETE'])
@admin_required
def delete_user(user_id):
    if user_id == session.get('user_id'):
        return jsonify({"error": "Anda tidak dapat menghapus akun Anda sendiri."}), 403

    user_ref = fdb.collection('users').document(user_id)
    if not user_ref.get().exists:
        return jsonify({"error": "Pengguna tidak ditemukan."}), 404

    try:
        user_ref.delete()
        return jsonify({"message": "Pengguna berhasil dihapus."}), 200
    except Exception as e:
        return jsonify({"error": f"Gagal menghapus pengguna: {str(e)}"}), 500

@app.route('/api/user/update/<string:user_id>', methods=['POST'])
@admin_required
def update_user(user_id):
    user_ref = fdb.collection('users').document(user_id)
    if not user_ref.get().exists:
        return jsonify({"error": "Pengguna tidak ditemukan."}), 404

    fullname = request.form.get('fullname')
    role = request.form.get('role')
    superior_id_str = request.form.get('superior_id')

    if not fullname or not role:
        return jsonify({"error": "Nama lengkap dan peran harus diisi."}), 400

    if user_id == session.get('user_id') and role != 'admin':
        return jsonify({"error": "Anda tidak dapat mengubah peran Anda sendiri dari admin."}), 403

    try:
        user_ref.update({
            'fullname': fullname,
            'role': role,
            'superior_id': superior_id_str if superior_id_str else None
        })
        return jsonify({"message": "Data pengguna berhasil diperbarui."}), 200
    except Exception as e:
        return jsonify({"error": f"Gagal memperbarui pengguna: {str(e)}"}), 500


@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('serve_login_page'))

# ==========================================
# ROUTES UNTUK MENYAJIKAN HALAMAN HTML
# ==========================================
@app.route('/')
def serve_login_page():
    return render_template('LOGIN.html')

@app.route('/register.html')
def serve_register_page():
    return render_template('register.html')

@app.route('/admin/dashboard.html')
@admin_required
def serve_admin_dashboard():
    return render_template('admin/dashboard.html', user_name=session.get('user_name', 'Admin'))

@app.route('/admin/kelola-pengguna.html')
@admin_required
def serve_admin_kelola_pengguna():
    return render_template('admin/kelola-pengguna.html', user_name=session.get('user_name', 'Admin'))

@app.route('/atasan/dashboard.html')
@login_required
def serve_atasan_dashboard():
    return render_template('atasan/dashboard.html', user_name=session.get('user_name', 'Atasan'))

@app.route('/atasan/tim-saya.html')
@login_required
def serve_atasan_tim_saya():
    if session.get('user_role') != 'atasan':
        return "Akses Ditolak", 403
    return render_template('atasan/tim-saya.html', user_name=session.get('user_name', 'Atasan'))

@app.route('/atasan/jadwal-rapat.html')
@login_required
def serve_atasan_jadwal_rapat():
    if session.get('user_role') != 'atasan':
        return "Akses Ditolak", 403
    return render_template('atasan/jadwal-rapat.html', user_name=session.get('user_name', 'Atasan'))

@app.route('/atasan/kalender-kegiatan.html')
@login_required
def serve_atasan_kalender_kegiatan():
    if session.get('user_role') != 'atasan':
        return "Akses Ditolak", 403
    return render_template('atasan/kalender-kegiatan.html', user_name=session.get('user_name', 'Atasan'))

@app.route('/atasan/kelola-pengumuman.html')
@login_required
def serve_atasan_kelola_pengumuman():
    if session.get('user_role') != 'atasan':
        return "Akses Ditolak", 403
    return render_template('atasan/kelola-pengumuman.html', user_name=session.get('user_name', 'Atasan'))

@app.route('/atasan/persetujuan.html')
@login_required
def serve_atasan_persetujuan():
    if session.get('user_role') != 'atasan':
        return "Akses Ditolak", 403
    return render_template('atasan/persetujuan.html', user_name=session.get('user_name', 'Atasan'))

@app.route('/USER/dashboard.html')
@login_required
def serve_user_dashboard():
    return render_template('USER/dashboard.html', user_name=session.get('user_name', 'Pengguna'))

@app.route('/USER/direktori-staf.html')
@login_required
def serve_user_direktori():
    return render_template('USER/direktori-staf.html', user_name=session.get('user_name', 'Pengguna'))

@app.route('/USER/bantuan.html')
@login_required
def serve_user_bantuan():
    return render_template('USER/bantuan.html', user_name=session.get('user_name', 'Pengguna'))

@app.route('/USER/alat-bantuan.html')
@login_required
def serve_user_alat():
    return render_template('USER/alat-bantuan.html', user_name=session.get('user_name', 'Pengguna'))

@app.route('/USER/profile.html')
@login_required
def serve_user_profile():
    return render_template('USER/profile.html', user_name=session.get('user_name', 'Pengguna'), user_email=session.get('user_email', ''))

@app.route('/USER/jadwal-rapat.html')
@login_required
def serve_user_jadwal_rapat():
    return render_template('USER/jadwal-rapat.html', user_name=session.get('user_name', 'Pengguna'))

@app.route('/USER/kalender-kegiatan.html')
@login_required
def serve_user_kalender_kegiatan():
    return render_template('USER/kalender-kegiatan.html', user_name=session.get('user_name', 'Pengguna'))

@app.route('/admin/jadwal-rapat.html')
@admin_required
def serve_admin_jadwal_rapat():
    return render_template('admin/jadwal-rapat.html', user_name=session.get('user_name', 'Admin'))

@app.route('/admin/kalender-kegiatan.html')
@admin_required
def serve_admin_kalender_kegiatan():
    return render_template('admin/kalender-kegiatan.html', user_name=session.get('user_name', 'Admin'))

@app.route('/admin/lapor-kendala.html')
@admin_required
def serve_admin_lapor_kendala():
    return render_template('admin/lapor-kendala.html', user_name=session.get('user_name', 'Admin'))

@app.route('/admin/kelola-pengumuman.html')
@admin_required
def serve_admin_kelola_pengumuman():

   return render_template('admin/kelola-pengumuman.html', user_name=session.get('user_name', 'Admin'))

@app.route('/api/pengumuman', methods=['GET'])
@login_required
def get_announcements():
    docs = fdb.collection('pengumuman').stream()
    hasil = []
    for d in docs:
        a = d.to_dict()
        hasil.append({
            'id': d.id,
            'title': a.get('title'),
            'content': a.get('content'),
            'category': a.get('category', 'indigo'),
            'date': a.get('date')
        })
    hasil.reverse()  # terbaru dulu
    return jsonify(hasil)

@app.route('/api/pengumuman', methods=['POST'])
@login_required
def add_announcement():
    data = request.get_json(silent=True) or {}
    title = data.get('title')
    content = data.get('content')
    category = data.get('category', 'indigo')

    if not title or not content:
        return jsonify({"error": "Judul dan konten wajib diisi."}), 400

    try:
        fdb.collection('pengumuman').document().set({
            'title': title,
            'content': content,
            'category': category,
            'date': datetime.datetime.now().strftime('%d %b %Y %H:%M')
        })
        return jsonify({"message": "Pengumuman berhasil ditambahkan!"}), 201
    except Exception as e:
        return jsonify({"error": f"Gagal menambah pengumuman: {str(e)}"}), 500

@app.route('/api/pengumuman/<string:ann_id>', methods=['DELETE'])
@login_required
def delete_announcement(ann_id):
    doc_ref = fdb.collection('pengumuman').document(ann_id)
    if not doc_ref.get().exists:
        return jsonify({"error": "Pengumuman tidak ditemukan."}), 404

    try:
        doc_ref.delete()
        return jsonify({"message": "Pengumuman berhasil dihapus!"}), 200
    except Exception as e:
        return jsonify({"error": f"Gagal menghapus pengumuman: {str(e)}"}), 500

@app.route('/api/meetings', methods=['GET'])
@login_required
def get_meetings():
    docs = fdb.collection('jadwal_rapat').stream()
    hasil = []
    for d in docs:
        m = d.to_dict()
        hasil.append({
            'id': d.id,
            'judul': m.get('judul'),
            'tanggal_raw': m.get('tanggal'),
            'tanggal': datetime.datetime.strptime(m.get('tanggal'), '%Y-%m-%d').strftime('%d %b %Y') if m.get('tanggal') else '',
            'waktu': m.get('waktu'),
            'peserta': m.get('peserta')
        })
    hasil.sort(key=lambda m: (m['tanggal_raw'] or '', m['waktu'] or ''))
    for h in hasil:
        h.pop('tanggal_raw', None)
    return jsonify(hasil)

@app.route('/api/meetings', methods=['POST'])
@admin_required
def add_meeting():
    judul = request.form.get('judul_rapat')
    tanggal_str = request.form.get('tanggal_rapat')
    waktu_str = request.form.get('waktu_rapat')
    peserta = request.form.get('peserta_rapat')

    if not all([judul, tanggal_str, waktu_str]):
        return jsonify({"error": "Judul, tanggal, dan waktu harus diisi."}), 400

    try:
        # Validasi format saja, disimpan tetap sebagai string 'YYYY-MM-DD' dan 'HH:MM'
        datetime.datetime.strptime(tanggal_str, '%Y-%m-%d')
        datetime.datetime.strptime(waktu_str, '%H:%M')

        fdb.collection('jadwal_rapat').document().set({
            'judul': judul,
            'tanggal': tanggal_str,
            'waktu': waktu_str,
            'peserta': peserta
        })

        return jsonify({"message": "Jadwal rapat berhasil ditambahkan."}), 201
    except Exception as e:
        return jsonify({"error": f"Gagal menambah jadwal: {str(e)}"}), 500

@app.route('/api/meetings/<string:meeting_id>', methods=['DELETE'])
@admin_required
def delete_meeting(meeting_id):
    doc_ref = fdb.collection('jadwal_rapat').document(meeting_id)
    if not doc_ref.get().exists:
        return jsonify({"error": "Jadwal rapat tidak ditemukan."}), 404
    try:
        doc_ref.delete()
        return jsonify({"message": "Jadwal rapat berhasil dihapus."}), 200
    except Exception as e:
        return jsonify({"error": f"Gagal menghapus jadwal: {str(e)}"}), 500


# ===================== PDF Panduan Portal =====================
@app.route('/api/panduan-portal', methods=['GET'])
@login_required
def download_panduan_portal():
    """Generate and serve PDF user guide for the portal."""
    try:
        from docx import Document
        from docx.shared import Inches, Pt, Cm, RGBColor
        from docx.enum.text import WD_ALIGN_PARAGRAPH
        import io
        
        doc = Document()
        
        # Style setup
        style = doc.styles['Normal']
        font = style.font
        font.name = 'Calibri'
        font.size = Pt(11)
        style.paragraph_format.space_after = Pt(6)
        style.paragraph_format.line_spacing = 1.15
        
        # Title
        title = doc.add_heading('BUKU PANDUAN PENGGUNA PORTAL KARYAWAN', level=0)
        title.alignment = WD_ALIGN_PARAGRAPH.CENTER
        for run in title.runs:
            run.font.color.rgb = RGBColor(0x07, 0x59, 0x85)  # corporate-700
            run.font.size = Pt(24)
        
        subtitle = doc.add_paragraph('Sistem Informasi Kantor - Versi 3.2.0')
        subtitle.alignment = WD_ALIGN_PARAGRAPH.CENTER
        subtitle.runs[0].font.size = Pt(12)
        subtitle.runs[0].font.color.rgb = RGBColor(0x64, 0x74, 0x8B)  # slate-500
        
        doc.add_paragraph('')  # spacer
        
        # Table of Contents
        doc.add_heading('DAFTAR ISI', level=1)
        toc_items = [
            '1. Pendahuluan & Login',
            '2. Dashboard (Beranda Utama)',
            '3. Tugas Saya - Manajemen Tugas Pribadi & dari Atasan',
            '4. Direktori Staf',
            '5. Alat Bantuan Dokumen (Konversi & Ringkasan)',
            '6. Jadwal Rapat',
            '7. Kalender Kegiatan',
            '8. Profil Saya & Pengaturan Akun',
            '9. Pusat Bantuan & Layanan IT',
            '10. Tips & Trik Produktivitas'
        ]
        for item in toc_items:
            p = doc.add_paragraph(item)
            p.paragraph_format.space_after = Pt(2)
        
        doc.add_page_break()
        
        # Chapter 1
        doc.add_heading('1. PENDAHULUAN & LOGIN', level=1)
        doc.add_paragraph(
            'Portal Karyawan adalah sistem informasi terintegrasi untuk mengelola aktivitas kerja harian, '
            'tugas, jadwal rapat, dan komunikasi internal kantor. Sistem ini dirancang dengan antarmuka '
            'modern yang responsif dan mudah digunakan di berbagai perangkat (desktop, tablet, mobile).'
        )
        doc.add_paragraph('Fitur utama:')
        features = [
            'Manajemen tugas real-time (diberikan atasan & pribadi)',
            'Kalender kegiatan & jadwal rapat terintegrasi',
            'Konversi dokumen (PDF ↔ Word) & peringkasan otomatis',
            'Notulensi rapat dari video/audio (speech-to-text)',
            'Direktori staf & struktur organisasi',
            'Pengumuman kedinasan berwarna',
            'Profil pengguna dengan foto & biodata lengkap'
        ]
        for f in features:
            doc.add_paragraph(f, style='List Bullet')
        
        doc.add_heading('Cara Login', level=2)
        login_steps = [
            'Buka browser dan akses alamat portal (misal: http://localhost:5000)',
            'Masukkan email perusahaan Anda',
            'Masukkan kata sandi',
            'Klik tombol "Masuk"',
            'Sistem akan mengarahkan ke dashboard sesuai peran (Admin/Atasan/Staf)'
        ]
        for i, step in enumerate(login_steps, 1):
            doc.add_paragraph(f'{step}', style='List Number')
        
        doc.add_paragraph(
            'Catatan: Jika lupa kata sandi, hubungi Helpdesk IT (Ext: 101/102 atau email helpdesk@perusahaan.co.id).'
        )
        
        # Chapter 2
        doc.add_heading('2. DASHBOARD (BERANDA UTAMA)', level=1)
        doc.add_paragraph(
            'Dashboard adalah halaman pertama yang muncul setelah login. Menampilkan ringkasan:'
        )
        dash_items = [
            'Statistik Tugas: Aktif, Selesai, Pengumuman',
            'Daftar 5 tugas terbaru yang diberikan atasan',
            'Pengumuman kedinasan terbaru (maksimal 5)',
            'Navigasi cepat ke fitur-fitur utama via sidebar'
        ]
        for item in dash_items:
            doc.add_paragraph(item, style='List Bullet')
        
        doc.add_paragraph(
            'Klik "Lihat Semua" pada bagian Tugas Terbaru untuk membuka halaman "Tugas Saya" lengkap dengan filter status.'
        )
        
        # Chapter 3
        doc.add_heading('3. TUGAS SAYA - MANAJEMEN TUGAS PRIBADI & DARI ATASAN', level=1)
        doc.add_paragraph(
            'Halaman ini menampilkan semua tugas Anda dalam tabel interaktif dengan fitur:'
        )
        task_features = [
            'Filter status: Semua / Belum Dikerjakan / Sedang Dikerjakan / Selesai',
            'Form tambah tugas pribadi (judul, deskripsi, prioritas, deadline)',
            'Edit & hapus tugas pribadi (tugas dari atasan tidak bisa diedit/dihapus)',
            'Ubah status tugas via dropdown (real-time update)',
            'Tampilkan nama pemberi tugas (atasan)',
            'Sinkronisasi real-time via Firebase (perubahan otomatis tanpa refresh)'
        ]
        for f in task_features:
            doc.add_paragraph(f, style='List Bullet')
        
        doc.add_heading('Prioritas Tugas', level=2)
        doc.add_paragraph('Tinggi (Merah) - Mendesak, harus diselesaikan segera')
        doc.add_paragraph('Sedang (Kuning) - Biasa, sesuai jadwal')
        doc.add_paragraph('Rendah (Abu-abu) - Fleksibel, tidak terburu-buru')
        
        # Chapter 4
        doc.add_heading('4. DIREKTORI STAF', level=1)
        doc.add_paragraph(
            'Menampilkan daftar seluruh karyawan dengan informasi: nama, email, peran (Admin/Atasan/Staf), '
            'dan atasan langsung. Dilengkapi pencarian real-time.'
        )
        
        # Chapter 5
        doc.add_heading('5. ALAT BANTUAN DOKUMEN', level=1)
        doc.add_paragraph('Tiga fitur konversi & analisis dokumen:')
        tools = [
            'PDF ke Word (.docx) - Konversi file PDF menjadi dokumen Word yang bisa diedit',
            'Word ke PDF - Konversi .docx ke PDF (membutuhkan MS Word terinstal di server)',
            'Ringkas Dokumen - Upload .docx, sistem akan merangkum isinya otomatis menggunakan NLP (LexRank + Sastrawi untuk Bahasa Indonesia)'
        ]
        for t in tools:
            doc.add_paragraph(t, style='List Bullet')
        
        doc.add_paragraph(
            'Catatan: File hasil konversi/ringkasan diunduh otomatis. Pastikan popup tidak diblokir browser.'
        )
        
        # Chapter 6
        doc.add_heading('6. JADWAL RAPAT', level=1)
        doc.add_paragraph(
            'Kelola jadwal rapat kantor. Admin bisa menambah/hapus jadwal. Semua pengguna bisa melihat jadwal.'
        )
        meeting_features = [
            'Form tambah rapat: Judul, Tanggal, Waktu, Peserta',
            'Daftar rapat terurut kronologis',
            'Hapus jadwal (hanya Admin)',
            'Tampilan terintegrasi di Kalender Kegiatan'
        ]
        for f in meeting_features:
            doc.add_paragraph(f, style='List Bullet')
        
        # Chapter 7
        doc.add_heading('7. KALENDER KEGIATAN', level=1)
        doc.add_paragraph(
            'Kalender bulanan interaktif menampilkan:'
        )
        cal_items = [
            'Pengumuman (berdasarkan tanggal & waktu pelaksanaan)',
            'Jadwal Rapat (berdasarkan tanggal & waktu rapat)',
            'Hari Libur Nasional 2026 (merah)',
            'Hari ini (highlight biru)',
            'Navigasi bulan Prev/Next/Today',
            'Maksimal 3 event per hari, keterangan "+N lagi..." jika lebih'
        ]
        for item in cal_items:
            doc.add_paragraph(item, style='List Bullet')
        
        doc.add_paragraph(
            'Catatan: Tanggal pelaksanaan pengumuman diatur di "Kelola Pengumuman" (Admin). '
            'Jadwal rapat diatur di "Jadwal Rapat" (Admin).'
        )
        
        # Chapter 8
        doc.add_heading('8. PROFIL SAYA & PENGATURAN AKUN', level=1)
        doc.add_paragraph('Dua tab utama:')
        
        doc.add_heading('Biodata Pribadi', level=2)
        bio_fields = [
            'Foto Profil (klik ikon kamera untuk upload/ganti)',
            'Nama Lengkap, NRP (angka), Asal, Gender (Laki-laki/Perempuan)',
            'Email (@gmail.com), Nomor Telepon (angka)',
            'Data tersimpan permanen di Firestore, tetap ada setelah logout/login'
        ]
        for f in bio_fields:
            doc.add_paragraph(f, style='List Bullet')
        
        doc.add_heading('Ubah Kata Sandi', level=2)
        doc.add_paragraph('Masukkan kata sandi lama, kata sandi baru (min. 6 karakter), dan konfirmasi.')
        
        # Chapter 9
        doc.add_heading('9. PUSAT BANTUAN & LAYANAN IT', level=1)
        doc.add_paragraph('Kontak bantuan:')
        contacts = [
            'Hotline: Ext Internal 101 / 102',
            'Email: helpdesk@perusahaan.co.id',
            'Formulir Tiket Bantuan di halaman ini (kategori: IT/Administrasi/Sarana/Lainnya)'
        ]
        for c in contacts:
            doc.add_paragraph(c, style='List Bullet')
        
        doc.add_paragraph(
            'Tiket yang dikirim akan diproses tim Helpdesk IT. Pastikan deskripsi kendala detail '
            '(kronologi, waktu, dampak) agar penanganan lebih cepat.'
        )
        
        # Chapter 10
        doc.add_heading('10. TIPS & TRIK PRODUKTIVITAS', level=1)
        tips = [
            'Gunakan filter status di "Tugas Saya" untuk fokus pada tugas "Sedang Dikerjakan"',
            'Atur deadline realistis agar terlihat di Kalender Kegiatan',
            'Upload foto profil agar mudah dikenali di Direktori Staf',
            'Manfaatkan "Ringkas Dokumen" untuk membaca laporan panjang singkat',
            'Cek Kalender Kegiatan mingguan untuk planning jadwal',
            'Gunakan mode mobile (hamburger menu) di smartphone untuk akses cepat',
            'Logout hanya saat diperlukan - sesi tetap aktif untuk kemudahan akses'
        ]
        for tip in tips:
            doc.add_paragraph(tip, style='List Bullet')
        
        # Footer
        doc.add_paragraph('')
        doc.add_paragraph('')
        footer = doc.add_paragraph('—')
        footer.alignment = WD_ALIGN_PARAGRAPH.CENTER
        footer = doc.add_paragraph('Portal Karyawan - Sistem Informasi Kantor')
        footer.alignment = WD_ALIGN_PARAGRAPH.CENTER
        footer.runs[0].font.size = Pt(10)
        footer.runs[0].font.color.rgb = RGBColor(0x94, 0xA3, 0xB8)
        footer = doc.add_paragraph('Versi 3.2.0 | Dikembangkan untuk kebutuhan internal')
        footer.alignment = WD_ALIGN_PARAGRAPH.CENTER
        footer.runs[0].font.size = Pt(9)
        footer.runs[0].font.color.rgb = RGBColor(0x94, 0xA3, 0xB8)
        
        # Save to BytesIO
        buffer = io.BytesIO()
        doc.save(buffer)
        buffer.seek(0)
        
        from flask import send_file
        return send_file(
            buffer,
            as_attachment=True,
            download_name='Panduan_Portal_Karyawan.docx',
            mimetype='application/vnd.openxmlformats-officedocument.wordprocessingml.document'
        )
        
    except Exception as e:
        return jsonify({"error": f"Gagal generate panduan: {str(e)}"}), 500


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)