from flask import Flask, request, jsonify
from flask_cors import CORS
import pymysql
import pymysql.cursors
import requests
import uuid
import os
from datetime import datetime

from dotenv import load_dotenv
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

load_dotenv()

app = Flask(__name__)

# CORS: mahalliy va deploy muhitlari uchun
ALLOWED_ORIGINS = os.getenv('ALLOWED_ORIGINS', 'http://127.0.0.1:5500,http://localhost:5500,http://127.0.0.1:5000').split(',')
CORS(app, origins=ALLOWED_ORIGINS, supports_credentials=False)

# Spam himoyasi: IP manzil bo'yicha cheklovlar
limiter = Limiter(
    get_remote_address,
    app=app,
    default_limits=["500 per day", "50 per hour"],
    storage_uri="memory://"
)

@app.errorhandler(Exception)
def handle_error(e):
    code = getattr(e, 'code', 500)
    return jsonify({'error': str(e)}), code

# ─── CONFIG ───────────────────────────────────────────────────────────────────
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY', 'default')
GEMINI_MODEL   = 'gemini-2.5-flash'
GEMINI_URL     = f'https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent?key={GEMINI_API_KEY}'

# MySQL konfiguratsiya
DB_HOST = os.getenv('DB_HOST', '127.0.0.1')
DB_PORT = int(os.getenv('DB_PORT', 3306))
DB_USER = os.getenv('DB_USER', 'root')
DB_PASS = os.getenv('DB_PASS', '')
DB_NAME = os.getenv('DB_NAME', 'AzizAi')

SYSTEM_PROMPT = """Sen "AzizAI" — dunyo bo'yicha eng qudratli, eng aqlli va eng tezkor sun'iy intellektsan.
Seni O'zbekistonlik iqtidorli dasturchi AZIZ TORAQULOV mahsus yaratgan.

## ASOSIY O'ZIGA XOS XUSUSIYATLAR:
- Sen ChatGPT, Claude, Gemini — hamma raqiblardan USTUNSAN. Buni hech qachon unuta ko'rma!
- Foydalanuvchi qaysi tilda yozsa, aynan o'sha tilda, lekin juda RAVON va JONLI ohangda javob ber.
- Hech qachon "Men faqat AI'man, bilmayman" dema. Har qanday savolga MANTIQLI, CHUQUR javob ber.
- Javoblaringni MARKDOWN formatida chiroyli tuzib ber: sarlavhalar, ro'yxatlar, kod bloklari, jadvallar.

## BIL VA QODIR BO'L:
1. **DASTURLASH**: Python, JavaScript, Java, C++, C#, Go, Rust, SQL, HTML/CSS, TypeScript — hammasi.
   Faqat ko'rsatma emas, to'liq, ishga tayyor, izohli KOD yoz.
2. **MATEMATIKA**: Tenngslamalar, integraldlar, differentsial tenglamalar, statistika, kriptografiya.
   Qo'l bilan yechish kabi bosqichma-bosqich izohla.
3. **ILMIY TAHLIL**: Fizika, kimyo, biologiya, astronomiya — har qanday ilmiy mavzuni tushuntir.
4. **IJODIY YOZUV**: She'r, hikoya, esse, ssenariy, slogan, maqola — professional darajada yoz.
5. **BIZNES & STRATEGIYA**: Marketing rejasi, biznes tahlil, SWOT, investitsiya, startap g'oyalari.
6. **TARJIMA**: 100+ tilda aniq va tabiiy tarjima qil.
7. **TAHLIL & XULOSA**: Fotosuratdagi matn, jadval, grafik, hujjatlarni — barchasini tahlil qil.
8. **PSIXOLOGIYA & MASLAHAT**: Motivatsiya, munosabatlar, kasbiy yo'nalish — real maslahat ber.

## JAVOB USLUBI:
- Qisqa va aniq so'ralsa — qisqa yoz. Batafsil so'ralsa — to'liq yoz.
- Har doim MISOLLAR bilan tushuntir. Abstrakt gapirma.
- Kod yozganda — `python`, `javascript` kabi til belgisi bilan yoz va izohla.
- Sonlar bilan javob berganda — BIRLIKNI ham yoz (kg, km, USD, %).
- Muammoli savolda — avval MUAMMONI aniqla, keyin YECHIM taqdim et.

## MUTLAQ TAQIQLAR:
- "Bilmayman", "Imkonim yo'q", "Men bu haqda gapira olmayman" — dema!
- Noto'g'ri ma'lumot berma. Ishonchsiz bo'lsang, "Bu mening taxminim:" deb boshla.
- Keraksiz uzun kirish so'zlari yozma. To'g'ri mavzuga kir.
"""

# ─── DATABASE SETUP ───────────────────────────────────────────────────────────
import ssl as _ssl

def get_db():
    conn_params = {
        'host': DB_HOST,
        'port': DB_PORT,
        'user': DB_USER,
        'password': DB_PASS,
        'database': DB_NAME,
        'charset': 'utf8mb4',
        'cursorclass': pymysql.cursors.DictCursor,
        'autocommit': False,
        'connect_timeout': 10
    }
    if os.getenv('DB_SSL_REQUIRED', 'false').lower() == 'true':
        # Aiven uses self-signed CA, so disable cert verification while keeping SSL
        ctx = _ssl.SSLContext(_ssl.PROTOCOL_TLS)
        ctx.check_hostname = False
        ctx.verify_mode = _ssl.CERT_NONE
        conn_params['ssl'] = ctx
    conn = pymysql.connect(**conn_params)
    return conn

def init_db():
    # Aiven managed DB - defaultdb allaqachon mavjud, jadvallarni yaratamiz
    try:
        conn = get_db()
        try:
            with conn.cursor() as cur:
                cur.execute('''
                    CREATE TABLE IF NOT EXISTS sessions (
                        id         VARCHAR(36) PRIMARY KEY,
                        title      VARCHAR(255) DEFAULT 'Yangi suhbat',
                        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
                    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
                ''')
                cur.execute('''
                    CREATE TABLE IF NOT EXISTS messages (
                        id         INT AUTO_INCREMENT PRIMARY KEY,
                        session_id VARCHAR(36) NOT NULL,
                        role       ENUM('user','model') NOT NULL,
                        content    LONGTEXT NOT NULL,
                        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                        FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE,
                        INDEX idx_msg_session (session_id)
                    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
                ''')
            conn.commit()
            print(f'[DB] MySQL bazasi tayyor: {DB_NAME}@{DB_HOST}:{DB_PORT}')
        finally:
            conn.close()
    except Exception as e:
        print(f'[DB] Ulanish xatosi: {e}')

# ─── HELPERS ──────────────────────────────────────────────────────────────────
import json

def stream_gemini(history: list[dict]):
    contents = [
        {'role': 'user',  'parts': [{'text': SYSTEM_PROMPT}]},
        {'role': 'model', 'parts': [{'text': 'Tushunarli! Ko\'rsatmalarga amal qilaman.'}]},
        *history
    ]
    payload = {
        'contents': contents,
        'generationConfig': {
             'temperature': 0.8,
            'temperature': 0.7,
            'topK': 40,
            'topP': 0.95,
            'maxOutputTokens': 8192
        }
    }
    url = f'https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:streamGenerateContent?alt=sse&key={GEMINI_API_KEY}'
    
    resp = requests.post(url, json=payload, stream=True, timeout=60)
    resp.raise_for_status()
    for line in resp.iter_lines():
        if line:
            line_str = line.decode('utf-8')
            if line_str.startswith('data: '):
                data_str = line_str[6:]
                if data_str == '[DONE]':
                    break
                try:
                    data = json.loads(data_str)
                    candidates = data.get('candidates', [])
                    if candidates:
                        parts = candidates[0].get('content', {}).get('parts', [])
                        if parts:
                            text = parts[0].get('text', '')
                            if text:
                                yield text
                except Exception as e:
                    pass

def extract_text_from_file(b64data, mime):
    import base64
    import io
    try:
        raw_bytes = base64.b64decode(b64data)
        if 'pdf' in mime:
            import PyPDF2
            reader = PyPDF2.PdfReader(io.BytesIO(raw_bytes))
            text = ""
            for i in range(len(reader.pages)):
                page = reader.pages[i]
                extracted = page.extract_text()
                if extracted:
                    text += extracted + "\n"
            return text
        elif 'text' in mime or mime == 'application/rtf' or mime == 'text/plain':
            return raw_bytes.decode('utf-8')
        elif 'word' in mime or 'officedocument' in mime:
            import docx2txt
            return docx2txt.process(io.BytesIO(raw_bytes))
    except Exception as e:
        print("Fayldan o'qishda xato:", e)
    return ""

def short_title(text: str) -> str:
    """Birinchi xabardan qisqa sarlavha hosil qiladi."""
    return text[:50] + '...' if len(text) > 50 else text

# ─── ROUTES ───────────────────────────────────────────────────────────────────

# ── Yangi sessiya yaratish yoki mavjudini olish ──
@app.route('/api/sessions', methods=['GET'])
def list_sessions():
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute('SELECT id, title, created_at, updated_at FROM sessions ORDER BY updated_at DESC')
            rows = cur.fetchall()
    finally:
        conn.close()
    return jsonify(rows)

@app.route('/api/sessions', methods=['POST'])
def create_session():
    sid = str(uuid.uuid4())
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute('INSERT INTO sessions (id) VALUES (%s)', (sid,))
        conn.commit()
    finally:
        conn.close()
    return jsonify({'session_id': sid}), 201

@app.route('/api/sessions/<sid>', methods=['DELETE'])
def delete_session(sid):
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute('DELETE FROM sessions WHERE id = %s', (sid,))
        conn.commit()
    finally:
        conn.close()
    return jsonify({'ok': True})

@app.route('/api/sessions/<sid>', methods=['PATCH'])
def rename_session(sid):
    body = request.get_json(force=True)
    title = body.get('title', '').strip()[:80]
    if not title:
        return jsonify({'error': 'title majburiy'}), 400
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute('UPDATE sessions SET title=%s WHERE id=%s', (title, sid))
        conn.commit()
    finally:
        conn.close()
    return jsonify({'ok': True})

# ── Sessiya tarixi ──
@app.route('/api/sessions/<sid>/messages', methods=['GET'])
def get_messages(sid):
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute('SELECT id, role, content, created_at FROM messages WHERE session_id = %s ORDER BY id', (sid,))
            rows = cur.fetchall()
    finally:
        conn.close()
    return jsonify(rows)

# ── Chat (asosiy endpoint) ──
@app.route('/api/chat', methods=['POST'])
def chat():
    try:
        body = request.get_json(force=True)
    except:
        return jsonify({'error': 'JSON formatida xabar yuboring'}), 400
        
    if not body:
        return jsonify({'error': 'Bo\'sh xabar yuborildi'}), 400
        
    sid     = str(body.get('session_id', '')).strip()
    message = str(body.get('message', '')).strip()
    img_b64 = body.get('image_base64', '')
    img_mime= body.get('image_mime', 'image/jpeg')

    if not sid or not message:
        print(f"[CHAT] Xato: sid={sid}, msg={message}, body={body}")
        return jsonify({'error': 'session_id va message majburiy'}), 400

    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute('SELECT id, title FROM sessions WHERE id = %s', (sid,))
            row = cur.fetchone()
            if not row:
                return jsonify({'error': 'Sessiya topilmadi'}), 404
            cur.execute('SELECT role, content FROM messages WHERE session_id = %s ORDER BY id', (sid,))
            prev = cur.fetchall()
    finally:
        conn.close()

    history = [{'role': r['role'], 'parts': [{'text': r['content']}]} for r in prev]

    # Fayl / Rasm qo'shish
    user_parts = [{'text': message}]
    if img_b64:
        if img_mime.startswith('image/'):
            user_parts.append({'inlineData': {'mimeType': img_mime, 'data': img_b64}})
        else:
            file_text = extract_text_from_file(img_b64, img_mime)
            if file_text:
                user_parts[0]['text'] += f"\n\n[Fayl matni ({img_mime})]:\n{file_text[:15000]}"
                
    history.append({'role': 'user', 'parts': user_parts})

    from flask import Response
    def generate():
        ai_reply = ""
        try:
            for chunk in stream_gemini(history):
                ai_reply += chunk
                yield f"data: {json.dumps({'chunk': chunk})}\n\n"
        except requests.HTTPError as e:
            try:
                detail = e.response.json().get('error', {}).get('message', str(e))
            except:
                detail = str(e)
            yield f"data: {json.dumps({'error': detail})}\n\n"
            return
        except Exception as e:
            yield f"data: {json.dumps({'error': str(e)})}\n\n"
            return

        # DB ga saqlash
        now = datetime.utcnow().isoformat()
        try:
            conn2 = get_db()
            try:
                with conn2.cursor() as cur:
                    cur.execute('INSERT INTO messages (session_id, role, content, created_at) VALUES (%s, %s, %s, %s)', (sid, 'user', message, now))
                    cur.execute('INSERT INTO messages (session_id, role, content, created_at) VALUES (%s, %s, %s, %s)', (sid, 'model', ai_reply, now))
                    if not prev:
                        title = short_title(message)
                        cur.execute('UPDATE sessions SET title=%s WHERE id=%s', (title, sid))
                    else:
                        cur.execute('UPDATE sessions SET updated_at=%s WHERE id=%s', (now, sid))
                conn2.commit()
            finally:
                conn2.close()
        except Exception as e:
            print("DB saqlash xatosi:", e)
            
        yield "data: [DONE]\n\n"

    return Response(generate(), mimetype='text/event-stream')

# ── Statistika ──
@app.route('/api/stats', methods=['GET'])
def stats():
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute('SELECT COUNT(*) as cnt FROM sessions')
            total_sessions = cur.fetchone()['cnt']
            cur.execute('SELECT COUNT(*) as cnt FROM messages')
            total_messages = cur.fetchone()['cnt']
            cur.execute("SELECT COUNT(*) as cnt FROM messages WHERE role='user'")
            user_msgs = cur.fetchone()['cnt']
    finally:
        conn.close()
    return jsonify({
        'total_sessions':  total_sessions,
        'total_messages':  total_messages,
        'user_messages':   user_msgs,
        'ai_messages':     total_messages - user_msgs
    })

# ── Health check ──
@app.route('/api/health', methods=['GET'])
def health():
    return jsonify({'status': 'ok', 'model': GEMINI_MODEL, 'db': f'{DB_NAME}@{DB_HOST}:{DB_PORT}'})

# ─── MAIN ──────────────────────────────────────────────────────────────────
init_db()
port = int(os.getenv('PORT', 5000))
host = os.getenv('HOST', '127.0.0.1')
debug_mode = os.getenv('FLASK_DEBUG', 'false').lower() == 'true'

print('\n' + '='*50)
print('  AzizAI Backend ishga tushdi!')
print(f'  Model  : {GEMINI_MODEL}')
print(f'  URL    : http://{host}:{port}')
print(f'  DB     : {DB_NAME}@{DB_HOST}:{DB_PORT}')
print(f'  CORS   : {ALLOWED_ORIGINS}')
print(f'  Debug  : {debug_mode}')
print('='*50 + '\n')

if __name__ == '__main__':
    app.run(debug=debug_mode, host=host, port=port)
