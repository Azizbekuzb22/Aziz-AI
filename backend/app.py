from flask import Flask, request, jsonify, Response
from flask_cors import CORS
import pymysql
import pymysql.cursors
import requests
import uuid
import os
import json
import ssl as _ssl
from datetime import datetime

from dotenv import load_dotenv
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

load_dotenv()

app = Flask(__name__)

# CORS: mahalliy va deploy muhitlari uchun
ALLOWED_ORIGINS = os.getenv(
    'ALLOWED_ORIGINS',
    'http://127.0.0.1:5500,http://localhost:5500,http://127.0.0.1:5000,http://localhost:5000'
).split(',')
CORS(app, origins=ALLOWED_ORIGINS, supports_credentials=False)

# Spam himoyasi
limiter = Limiter(
    get_remote_address,
    app=app,
    default_limits=["500 per day", "60 per hour"],
    storage_uri="memory://"
)

@app.errorhandler(Exception)
def handle_error(e):
    code = getattr(e, 'code', 500)
    return jsonify({'error': str(e)}), code

# ─── CONFIG ───────────────────────────────────────────────────────────────────
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY', '')
GEMINI_MODEL   = 'gemini-2.5-flash'

# MySQL konfiguratsiya
DB_HOST = os.getenv('DB_HOST', '127.0.0.1')
DB_PORT = int(os.getenv('DB_PORT', 3306))
DB_USER = os.getenv('DB_USER', 'root')
DB_PASS = os.getenv('DB_PASS', '')
DB_NAME = os.getenv('DB_NAME', 'AzizAI')

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
2. **MATEMATIKA**: Tenglamalar, integrallar, differentsial tenglamalar, statistika, kriptografiya.
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

# ─── DATABASE ─────────────────────────────────────────────────────────────────

def get_db():
    conn_params = {
        'host':         DB_HOST,
        'port':         DB_PORT,
        'user':         DB_USER,
        'password':     DB_PASS,
        'database':     DB_NAME,
        'charset':      'utf8mb4',
        'cursorclass':  pymysql.cursors.DictCursor,
        'autocommit':   False,
        'connect_timeout': 15,
        'read_timeout':    30,
        'write_timeout':   30,
    }
    if os.getenv('DB_SSL_REQUIRED', 'false').lower() == 'true':
        ctx = _ssl.SSLContext(_ssl.PROTOCOL_TLS_CLIENT)
        ctx.check_hostname = False
        ctx.verify_mode = _ssl.CERT_NONE
        conn_params['ssl'] = ctx
    return pymysql.connect(**conn_params)


def init_db():
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

# Rasm yaratish so'rov kalitlari
IMAGE_KEYWORDS = [
    'rasm yarat', 'rasm chiqar', 'rasm chiz', 'rasm tort',
    'surat yarat', 'surat chiqar', 'chizib ber', 'tasvirla',
    'draw', 'generate image', 'create image', 'make image',
    'paint', 'illustrate', 'show me a picture', 'show picture',
    'rasmini yarat', 'rasmini chiqar', 'generate a', 'create a picture'
]

def is_image_request(message: str) -> bool:
    """Foydalanuvchi rasm so'rayotganini aniqlaydi."""
    msg_lower = message.lower()
    return any(kw in msg_lower for kw in IMAGE_KEYWORDS)

def get_image_prompt_via_gemini(user_message: str) -> str:
    """Foydalanuvchi so'rovidan inglizcha rasm tavsifi olamiz."""
    url = (
        f'https://generativelanguage.googleapis.com/v1beta/models/'
        f'gemini-2.0-flash:generateContent?key={GEMINI_API_KEY}'
    )
    payload = {
        'contents': [{'role': 'user', 'parts': [{'text':
            f"Convert this image request into a short, descriptive English prompt for an AI image generator. "
            f"Return ONLY the English prompt, nothing else, no explanations:\n\n{user_message}"
        }]}]
    }
    try:
        r = requests.post(url, json=payload, timeout=15)
        r.raise_for_status()
        data = r.json()
        prompt = data['candidates'][0]['content']['parts'][0]['text'].strip()
        return prompt[:400]  # max 400 character
    except Exception:
        # Fallback: to'g'ri foydalanuvchi matni
        return user_message[:300]

def generate_image_url(prompt: str) -> str:
    """Pollinations.ai orqali rasm URL si hosil qiladi (bepul, API kerak emas)."""
    import urllib.parse
    encoded = urllib.parse.quote(prompt)
    return f"https://image.pollinations.ai/prompt/{encoded}?width=1024&height=768&nologo=true&model=flux&seed={uuid.uuid4().int % 99999}"


def stream_gemini(history):
    """Gemini API ga SSE stream so'rovi yuboradi va matn bo'laklarini yield qiladi."""
    contents = [
        {'role': 'user',  'parts': [{'text': SYSTEM_PROMPT}]},
        {'role': 'model', 'parts': [{'text': "Tushunarli! Ko'rsatmalarga amal qilaman."}]},
        *history
    ]
    payload = {
        'contents': contents,
        'generationConfig': {
             'temperature': 0.7,
             'topK': 40,
             'topP': 0.95
        }
    }
    url = (
        f'https://generativelanguage.googleapis.com/v1beta/models/'
        f'{GEMINI_MODEL}:streamGenerateContent?alt=sse&key={GEMINI_API_KEY}'
    )

    resp = requests.post(url, json=payload, stream=True, timeout=90)
    resp.raise_for_status()

    for line in resp.iter_lines():
        if not line:
            continue
        line_str = line.decode('utf-8')
        if not line_str.startswith('data: '):
            continue
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
        except Exception:
            pass


def extract_text_from_file(b64data, mime):
    """PDF va Word fayllardan matn ajratib oladi."""
    import base64
    import io
    try:
        raw_bytes = base64.b64decode(b64data)
        if 'pdf' in mime:
            import PyPDF2
            reader = PyPDF2.PdfReader(io.BytesIO(raw_bytes))
            return '\n'.join(
                page.extract_text() or '' for page in reader.pages
            )
        elif 'text' in mime or mime in ('application/rtf', 'text/plain'):
            return raw_bytes.decode('utf-8', errors='replace')
        elif 'word' in mime or 'officedocument' in mime:
            import docx2txt
            return docx2txt.process(io.BytesIO(raw_bytes))
    except Exception as e:
        print(f"[FILE] O'qishda xato: {e}")
    return ''


def short_title(text: str) -> str:
    """Birinchi xabardan qisqa sarlavha hosil qiladi."""
    clean = text.strip().replace('\n', ' ')
    return clean[:50] + '...' if len(clean) > 50 else clean

# ─── ROUTES ───────────────────────────────────────────────────────────────────

@app.route('/api/sessions', methods=['GET'])
def list_sessions():
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute(
                'SELECT id, title, created_at, updated_at '
                'FROM sessions ORDER BY updated_at DESC'
            )
            rows = cur.fetchall()
    finally:
        conn.close()
    # datetime ob'ektlarini string ga aylantirish
    result = [dict(r) for r in rows]
    for r in result:
        for k in ('created_at', 'updated_at'):
            if r.get(k) and hasattr(r[k], 'isoformat'):
                r[k] = r[k].isoformat()  # type: ignore[union-attr]
    return jsonify(result)


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
    body: dict = request.get_json(force=True, silent=True) or {}
    raw_title: str = str(body.get('title', '')).strip()
    title: str = (raw_title[:100] if len(raw_title) > 100 else raw_title)
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


@app.route('/api/sessions/<sid>/messages', methods=['GET'])
def get_messages(sid):
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute(
                'SELECT id, role, content, created_at '
                'FROM messages WHERE session_id = %s ORDER BY id',
                (sid,)
            )
            rows = cur.fetchall()
    finally:
        conn.close()
    result = [dict(r) for r in rows]
    for r in result:
        if r.get('created_at') and hasattr(r['created_at'], 'isoformat'):
            r['created_at'] = r['created_at'].isoformat()  # type: ignore[union-attr]
    return jsonify(result)


@app.route('/api/chat', methods=['POST'])
@limiter.limit("30 per minute")
def chat():
    body = request.get_json(force=True, silent=True)
    if not body:
        return jsonify({'error': "JSON formatida xabar yuboring"}), 400

    sid      = str(body.get('session_id', '')).strip()
    message  = str(body.get('message', '')).strip()
    img_b64  = body.get('image_base64', '')
    img_mime = body.get('image_mime', 'image/jpeg')

    # Xabar yoki rasm bo'lishi shart
    if not sid or (not message and not img_b64):
        return jsonify({'error': 'session_id va message (yoki rasm) majburiy'}), 400

    if not GEMINI_API_KEY:
        return jsonify({'error': 'Server konfiguratsiya xatosi: API kalit topilmadi'}), 500

    # Sessiya mavjudligini tekshirish
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute('SELECT id FROM sessions WHERE id = %s', (sid,))
            if not cur.fetchone():
                return jsonify({'error': 'Sessiya topilmadi'}), 404
            cur.execute(
                'SELECT role, content FROM messages WHERE session_id = %s ORDER BY id',
                (sid,)
            )
            prev_rows = cur.fetchall()
    finally:
        conn.close()

    # Tarix: har bir qatorni aniq dict ga o'girish
    prev: list = [dict(r) for r in prev_rows]
    history: list = [
        {'role': str(r['role']), 'parts': [{'text': str(r['content'])}]}
        for r in prev
    ]

    # Yangi user xabari
    user_text = message or "Rasmga izoh bering"
    user_parts: list = [{'text': user_text}]

    if img_b64:
        if img_mime.startswith('image/'):
            inline_data: dict = {'inlineData': {'mimeType': img_mime, 'data': img_b64}}
            user_parts.append(inline_data)
        else:
            file_text = extract_text_from_file(img_b64, img_mime)
            if file_text:
                user_parts[0]['text'] += f"\n\n[Fayl matni ({img_mime})]:\n{file_text[:15000]}"

    history.append({'role': 'user', 'parts': user_parts})

    is_first = not prev

    # ── RASM YARATISH (Pollinations.ai) ──────────────────────────────────────
    if is_image_request(user_text) and not img_b64:
        def generate_img():
            try:
                # Gemini orqali inglizcha prompt yaratamiz
                eng_prompt = get_image_prompt_via_gemini(user_text)
                img_url = generate_image_url(eng_prompt)

                # DB ga saqlash
                now = datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')
                ai_reply = f"![Generated Image]({img_url})\n\n*Prompt: {eng_prompt}*"
                try:
                    db2 = get_db()
                    try:
                        with db2.cursor() as cur:
                            cur.execute(
                                'INSERT INTO messages (session_id, role, content, created_at) VALUES (%s, %s, %s, %s)',
                                (sid, 'user', user_text, now)
                            )
                            cur.execute(
                                'INSERT INTO messages (session_id, role, content, created_at) VALUES (%s, %s, %s, %s)',
                                (sid, 'model', ai_reply, now)
                            )
                            if is_first:
                                cur.execute('UPDATE sessions SET title=%s WHERE id=%s', (short_title(user_text), sid))
                            else:
                                cur.execute('UPDATE sessions SET updated_at=%s WHERE id=%s', (now, sid))
                        db2.commit()
                    finally:
                        db2.close()
                except Exception as db_err:
                    print(f"[DB] Saqlash xatosi: {db_err}")

                yield f"data: {json.dumps({'chunk': ai_reply}, ensure_ascii=False)}\n\n"
                yield "data: [DONE]\n\n"
            except Exception as e:
                yield f"data: {json.dumps({'error': str(e)})}\n\n"

        return Response(generate_img(), mimetype='text/event-stream',
                        headers={'X-Accel-Buffering': 'no', 'Cache-Control': 'no-cache'})
    # ─────────────────────────────────────────────────────────────────────────

    def generate():

        ai_reply = ""
        try:
            for chunk in stream_gemini(history):
                ai_reply += chunk
                yield f"data: {json.dumps({'chunk': chunk}, ensure_ascii=False)}\n\n"
        except requests.HTTPError as e:
            try:
                detail = e.response.json().get('error', {}).get('message', str(e))
            except Exception:
                detail = str(e)
            yield f"data: {json.dumps({'error': detail})}\n\n"
            return
        except Exception as e:
            yield f"data: {json.dumps({'error': str(e)})}\n\n"
            return

        if not ai_reply:
            empty_err = {"error": "Gemini bosh javob qaytardi"}
            yield f"data: {json.dumps(empty_err)}\n\n"
            return

        # DB ga saqlash
        now = datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')
        try:
            db2 = get_db()
            try:
                with db2.cursor() as cur:
                    cur.execute(
                        'INSERT INTO messages (session_id, role, content, created_at) VALUES (%s, %s, %s, %s)',
                        (sid, 'user', user_text, now)
                    )
                    cur.execute(
                        'INSERT INTO messages (session_id, role, content, created_at) VALUES (%s, %s, %s, %s)',
                        (sid, 'model', ai_reply, now)
                    )
                    if is_first:
                        cur.execute(
                            'UPDATE sessions SET title=%s WHERE id=%s',
                            (short_title(user_text), sid)
                        )
                    else:
                        cur.execute('UPDATE sessions SET updated_at=%s WHERE id=%s', (now, sid))
                db2.commit()
            finally:
                db2.close()
        except Exception as db_err:
            print(f"[DB] Saqlash xatosi: {db_err}")

        yield "data: [DONE]\n\n"

    return Response(generate(), mimetype='text/event-stream',
                    headers={'X-Accel-Buffering': 'no', 'Cache-Control': 'no-cache'})


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
        'total_sessions': total_sessions,
        'total_messages': total_messages,
        'user_messages':  user_msgs,
        'ai_messages':    total_messages - user_msgs
    })


@app.route('/api/health', methods=['GET'])
def health():
    # DB ulanishini tekshirish
    db_ok = False
    try:
        conn = get_db()
        conn.ping(reconnect=True)
        conn.close()
        db_ok = True
    except Exception as e:
        print(f"[HEALTH] DB ping xatosi: {e}")

    return jsonify({
        'status': 'ok' if db_ok else 'degraded',
        'model':  GEMINI_MODEL,
        'db':     f'{DB_NAME}@{DB_HOST}:{DB_PORT}',
        'db_ok':  db_ok
    }), 200 if db_ok else 503


# ─── MAIN ─────────────────────────────────────────────────────────────────────
init_db()

port       = int(os.getenv('PORT', 5000))
host       = os.getenv('HOST', '127.0.0.1')
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
