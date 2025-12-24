import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')
    #FLASK_ENV = os.getenv('FLASK_ENV', 'development')
    
    # Game settings
    NUM_PLAYERS = 6
    BOARD_RADIUS = 4



