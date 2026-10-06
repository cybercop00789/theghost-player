import os
os.system('gunicorn -b 0.0.0.0:7860 server:app')
