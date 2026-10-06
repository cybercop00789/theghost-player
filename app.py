import os
from flask import send_file
from server import app

# HF Spaces mounts at / — serve index at /
@app.route('/', methods=['GET'])
def root_index():
    try:
        return send_file('index.html')
    except Exception:
        return app.send_static_file('index.html')

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 7860))
    print(f"HF Spaces -> http://0.0.0.0:{port}/ (PORT={port})")
    app.run(host='0.0.0.0', port=port, threaded=True)
