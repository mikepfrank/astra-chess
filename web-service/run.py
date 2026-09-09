"""Native Windows/Linux entry point. Public deployment is a separate host-validation step."""
import argparse
import os
from urllib.parse import urlsplit


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=8788)
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--public', action='store_true', help='Enable binding for a separately configured HTTPS reverse proxy')
    args = parser.parse_args()
    if args.host not in ('127.0.0.1', '::1', 'localhost') and not args.public:
        parser.error('Non-loopback binding requires --public and an HTTPS ASTRA_ORIGIN.')
    if args.public and not os.getenv('ASTRA_ORIGIN', '').startswith('https://'):
        parser.error('Configure an HTTPS ASTRA_ORIGIN before enabling public binding.')
    if not os.getenv('ASTRA_ORIGIN'):
        os.environ['ASTRA_ORIGIN'] = f'http://127.0.0.1:{args.port}'
    import uvicorn
    from astra_web.app import create_app
    uvicorn.run(create_app(), host=args.host, port=args.port, workers=1, proxy_headers=False,
                access_log=False, limit_concurrency=64, timeout_keep_alive=5)
