import redis
from config import REDIS_CONFIG

redis_client = redis.Redis(
    host=REDIS_CONFIG['host'],
    port=REDIS_CONFIG['port'],
    db=REDIS_CONFIG['db'],
    password=REDIS_CONFIG.get('password',''),
    decode_responses=True,
    protocol=2,
    # redis-py 8 默认开启连接重试（指数退避），Redis 挂掉时会卡约 48s；
    # 这里关闭重试并设置超时，让限流/缓存快速失败而不是拖垮请求
    socket_connect_timeout=2,
    socket_timeout=2,
    retry=None,
)