import os
from flask import send_file
import gradio as gr
from server import app as flask_app

@flask_app.route('/')
def index():
    return send_file('index.html')

app = gr.mount_gradio_app(flask_app, gr.Blocks(), path='/gradio')

if __name__ == '__main__':
    import uvicorn
    uvicorn.run('app:app', host='0.0.0.0', port=7860)
