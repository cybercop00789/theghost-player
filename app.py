import os
import spaces
import gradio as gr

@spaces.GPU
def init_gpu(x):
    return x

init_gpu(1)
os.system("gunicorn -b 0.0.0.0:7860 server:app")
