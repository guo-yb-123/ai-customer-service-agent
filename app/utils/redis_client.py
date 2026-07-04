import redis
from config import REDIS_CONFIG

redis_client = redis.Redis(
    host=REDIS_CONFIG['host'],
    port=REDIS_CONFIG['port'],
    db=REDIS_CONFIG['db'],
    password=REDIS_CONFIG.get('password',''),
    decode_responses=True,
    protocol=2
)