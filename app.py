import os
import subprocess
import json
import wave
import uuid
from flask import Flask, request, render_template, jsonify, send_file
import vosk
from indic_transliteration import sanscript
from indic_transliteration.sanscript import transliterate

app = Flask(__name__)

UPLOAD_FOLDER = "uploads"
OUTPUT_FOLDER = "outputs"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(OUTPUT_FOLDER, exist_ok=True)

MODELS = {
    "en": "models/en",
    "hi": "models/hi"
}

ALLOWED_EXTENSIONS = {'mp4', 'avi', 'mov', 'mkv', 'webm'}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def extract_audio(video_path, audio_path):
    if os.path.exists(audio_path):
        os.remove(audio_path)
    command = [
        "ffmpeg", "-y",
        "-i", video_path,
        "-ar", "16000",
        "-ac", "1",
        "-f", "wav",
        audio_path
    ]
    subprocess.run(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

def transcribe_audio(audio_path, lang="en"):
    model_path = MODELS.get(lang)
    if not model_path or not os.path.exists(model_path):
        return {"error": f"Model not found for language '{lang}'."}

    wf = wave.open(audio_path, "rb")
    if wf.getnchannels() != 1 or wf.getsampwidth() != 2 or wf.getframerate() != 16000:
        return {"error": "Invalid audio format. Must be WAV mono PCM 16kHz."}

    model = vosk.Model(model_path)
    rec = vosk.KaldiRecognizer(model, wf.getframerate())
    rec.SetWords(True)

    results = []
    while True:
        data = wf.readframes(4000)
        if len(data) == 0:
            break
        if rec.AcceptWaveform(data):
            results.append(json.loads(rec.Result()))
    results.append(json.loads(rec.FinalResult()))
    wf.close()
    return results

def process_results(results):
    transcript = []
    for res in results:
        if "result" in res:
            transcript.extend(res["result"])
    return transcript

def format_ass_timestamp(seconds):
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    cs = int((seconds - int(seconds)) * 100)
    return f"{h:d}:{m:02d}:{s:02d}.{cs:02d}"

def ass_color(hex_color):
    hex_color = hex_color.lstrip('#')
    r = hex_color[0:2]
    g = hex_color[2:4]
    b = hex_color[4:6]
    return f"&H00{b}{g}{r}&"

def transliterate_word(word, lang):
    if lang == "hi":
        try:
            roman = transliterate(word, sanscript.DEVANAGARI, sanscript.ITRANS)
            roman = roman.replace("aa", "a").replace("ii", "i").replace("uu", "u")
            return roman
        except Exception:
            return word
    else:
        return word

def generate_ass(words, font="Arial", font_size=48, color="#FFFFFF", outline_color="#000000", alignment=2, lang="en", animation_style="zoom"):
    primary_color = ass_color(color)
    outline_color_ass = ass_color(outline_color)
    highlight_backcolor = "&H00000000"  # Transparent background

    playres_x = 1920
    playres_y = 1080
    margin_v = 100  # Position subtitles lower

    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {playres_x}
PlayResY: {playres_y}
Timer: 100.0000

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,{font},{font_size},{primary_color},{outline_color_ass},{highlight_backcolor},1,0,0,0,100,100,0,0,1,3,0,{alignment},10,10,{margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

    lines = []

    import random

    if animation_style == "default":
        # Show one word at a time with zoom animation
        for word in words:
            start_time = word["start"]
            end_time = word["end"]
            original_word = word["word"]
            display_word = transliterate_word(original_word, lang).upper()

            start = format_ass_timestamp(start_time)
            end = format_ass_timestamp(end_time)

            zoom_start = 0
            zoom_duration = 400
            tag = (
                r"{\an" + str(alignment) +
                r"\bord3" +
                r"\1c" + primary_color +
                r"\fscx50\fscy50" +
                r"\t(" + str(zoom_start) + "," + str(zoom_duration) + ",1,\\fscx100\\fscy100)" +
                r"}"
            )
            lines.append(f"Dialogue: 0,{start},{end},Default,,0,0,0,,{tag}{display_word}")

    else:
        # Group words into sentences of 2-4 words max for other animations
        groups = []
        current_group = []
        max_words_per_sentence = 4

        for i, w in enumerate(words):
            current_group.append(w)
            if len(current_group) >= random.randint(2, max_words_per_sentence) or i == len(words) - 1:
                groups.append(current_group)
                current_group = []

        for group in groups:
            start_time = group[0]["start"]
            end_time = group[-1]["end"]
            display_words = [transliterate_word(w["word"], lang).upper() for w in group]
            display_text = " ".join(display_words)

            start = format_ass_timestamp(start_time)
            end = format_ass_timestamp(end_time)

            if animation_style == "sprinkle":
                zoom_start = 0
                zoom_duration = 400
                jitter_x = random.randint(-30, 30)
                jitter_y = random.randint(-10, 10)
                x = playres_x // 2 + jitter_x
                y = playres_y - margin_v + jitter_y
                tag = (
                    r"{\an" + str(alignment) +
                    r"\bord3" +
                    r"\1c" + primary_color +
                    r"\fscx50\fscy50" +
                    r"\pos(" + str(x) + "," + str(y) + ")" +
                    r"\t(" + str(zoom_start) + "," + str(zoom_duration) + ",1,\\fscx100\\fscy100)" +
                    r"}"
                )
            elif animation_style == "slide":
                # Simple smooth side slide with subtle color
                x_start = -400
                x_end = playres_x // 2
                y = playres_y - margin_v
                color_tag = primary_color  # Use primary color for simplicity
                tag = (
                    r"{\an" + str(alignment) +
                    r"\bord3" +
                    r"\1c" + color_tag +
                    r"\pos(" + str(x_start) + "," + str(y) + ")" +
                    r"\t(0,600,1,\\pos(" + str(x_end) + "," + str(y) + "))" +
                    r"}"
                )
            elif animation_style == "fade":
                y_start = playres_y - margin_v + 20
                y_end = playres_y - margin_v
                x = playres_x // 2
                tag = (
                    r"{\an" + str(alignment) +
                    r"\bord3" +
                    r"\1c" + primary_color +
                    r"\fad(200,200)" +
                    r"\pos(" + str(x) + "," + str(y_start) + ")" +
                    r"\t(0,400,1,\\pos(" + str(x) + "," + str(y_end) + "))" +
                    r"}"
                )
            elif animation_style == "zoom":
                zoom_start = 0
                zoom_duration = 400
                tag = (
                    r"{\an" + str(alignment) +
                    r"\bord3" +
                    r"\1c" + primary_color +
                    r"\fscx50\fscy50" +
                    r"\t(" + str(zoom_start) + "," + str(zoom_duration) + ",1,\\fscx100\\fscy100)" +
                    r"}"
                )
            else:
                tag = (
                    r"{\an" + str(alignment) +
                    r"\bord3" +
                    r"\1c" + primary_color +
                    r"}"
                )

            lines.append(f"Dialogue: 0,{start},{end},Default,,0,0,0,,{tag}{display_text}")

    return header + "\n".join(lines)

from threading import Lock
update_lock = Lock()

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/upload", methods=["POST"])
def upload():
    if "video" not in request.files:
        return jsonify({"error": "No video file part"}), 400
        
    video_file = request.files["video"]
    lang = request.form.get("language", "en").lower()
    animation_style = request.form.get("animation", "default").lower()
    
    if lang not in MODELS:
        return jsonify({"error": "Invalid language choice"}), 400
        
    if video_file.filename == '':
        return jsonify({"error": "No selected file"}), 400
        
    if not allowed_file(video_file.filename):
        return jsonify({"error": "Invalid file type"}), 400

    unique_id = str(uuid.uuid4())
    ext = os.path.splitext(video_file.filename)[1]
    video_filename = os.path.join(UPLOAD_FOLDER, f"{unique_id}{ext}")
    video_file.save(video_filename)

    audio_filename = os.path.join(UPLOAD_FOLDER, f"{unique_id}.wav")
    extract_audio(video_filename, audio_filename)

    results = transcribe_audio(audio_filename, lang=lang)
    if isinstance(results, dict) and "error" in results:
        return jsonify(results), 500

    transcript = process_results(results)
    if not transcript:
        return jsonify({"error": "No subtitles generated."}), 500

    ass_path = os.path.join(OUTPUT_FOLDER, f"{unique_id}.ass")
    with open(ass_path, "w", encoding="utf-8") as f:
        f.write(generate_ass(
            transcript,
            font="Arial Black",
            font_size=56,
            color="#FFFFFF",
            outline_color="#000000",
            alignment=2,
            lang=lang,
            animation_style=animation_style
        ))

    output_path = os.path.join(OUTPUT_FOLDER, f"{unique_id}_subtitled.mp4")

    command = [
        "ffmpeg", "-y",
        "-i", video_filename,
        "-vf", f"ass={ass_path.replace(os.sep, '/')}",
        "-c:a", "copy",
        "-movflags", "+faststart",
        output_path
    ]

    result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if result.returncode != 0:
        print("FFmpeg error:", result.stderr.decode())
        return jsonify({"error": "Failed to add subtitles"}), 500

    return jsonify({
        "success": True,
        "unique_id": unique_id,
        "download_url": f"/download/{unique_id}",
        "preview_url": f"/preview/{unique_id}"
    })

@app.route("/update_animation", methods=["POST"])
def update_animation():
    data = request.json
    unique_id = data.get("unique_id")
    animation_style = data.get("animation_style", "default")
    lang = data.get("language", "en")

    if not unique_id:
        return jsonify({"error": "Missing unique_id"}), 400

    video_filename = None
    for ext in ALLOWED_EXTENSIONS:
        path = os.path.join(UPLOAD_FOLDER, f"{unique_id}.{ext}")
        if os.path.exists(path):
            video_filename = path
            break

    if not video_filename:
        return jsonify({"error": "Original video not found"}), 404

    audio_filename = os.path.join(UPLOAD_FOLDER, f"{unique_id}.wav")
    if not os.path.exists(audio_filename):
        extract_audio(video_filename, audio_filename)

    results = transcribe_audio(audio_filename, lang=lang)
    if isinstance(results, dict) and "error" in results:
        return jsonify(results), 500

    transcript = process_results(results)
    if not transcript:
        return jsonify({"error": "No subtitles generated."}), 500

    with update_lock:
        ass_path = os.path.join(OUTPUT_FOLDER, f"{unique_id}.ass")
        with open(ass_path, "w", encoding="utf-8") as f:
            f.write(generate_ass(
                transcript,
                font="Arial Black",
                font_size=56,
                color="#FFFFFF",
                outline_color="#000000",
                alignment=2,
                lang=lang,
                animation_style=animation_style
            ))

        output_path = os.path.join(OUTPUT_FOLDER, f"{unique_id}_subtitled.mp4")

        command = [
            "ffmpeg", "-y",
            "-i", video_filename,
            "-vf", f"ass={ass_path.replace(os.sep, '/')}",
            "-c:a", "copy",
            "-movflags", "+faststart",
            output_path
        ]

        result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if result.returncode != 0:
            print("FFmpeg error:", result.stderr.decode())
            return jsonify({"error": "Failed to update subtitles"}), 500

    return jsonify({
        "success": True,
        "download_url": f"/download/{unique_id}",
        "preview_url": f"/preview/{unique_id}"
    })

@app.route("/download/<unique_id>")
def download_video(unique_id):
    video_filename = None
    for ext in ALLOWED_EXTENSIONS:
        path = os.path.join(UPLOAD_FOLDER, f"{unique_id}.{ext}")
        if os.path.exists(path):
            video_filename = path
            break

    if not video_filename:
        return jsonify({"error": "Original video not found"}), 404

    output_path = os.path.join(OUTPUT_FOLDER, f"{unique_id}_subtitled.mp4")
    if not os.path.exists(output_path):
        return jsonify({"error": "Subtitled video not found"}), 404

    return send_file(output_path, as_attachment=True, download_name="subtitled_video.mp4")

@app.route("/preview/<unique_id>")
def preview_video(unique_id):
    output_path = os.path.join(OUTPUT_FOLDER, f"{unique_id}_subtitled.mp4")
    if not os.path.exists(output_path):
        return jsonify({"error": "File not found"}), 404
        
    return send_file(output_path, mimetype="video/mp4")

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
