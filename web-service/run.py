"""Native Windows/Linux entry point. Public deployment is a separate host-validation step."""
import argparse
import os
from pathlib import Path


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=8788)
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--public', action='store_true', help='Enable binding for a separately configured HTTPS reverse proxy')
    parser.add_argument('--proxy-headers', action='store_true',
                        help='Trust forwarded client addresses and scheme only from a reverse proxy at 127.0.0.1')
    args = parser.parse_args()
    from astra_web.local_setup import load_local_environment, LocalSetupError
    try:
        load_local_environment(Path(__file__).resolve().parent)
    except LocalSetupError as error:
        parser.error(str(error))
    if args.host not in ('127.0.0.1', '::1', 'localhost') and not args.public:
        parser.error('Non-loopback binding requires --public and an HTTPS ASTRA_ORIGIN.')
    if args.public and not os.getenv('ASTRA_ORIGIN', '').startswith('https://'):
        parser.error('Configure an HTTPS ASTRA_ORIGIN before enabling public binding.')
    if not os.getenv('ASTRA_ORIGIN'):
        os.environ['ASTRA_ORIGIN'] = f'http://127.0.0.1:{args.port}'
    import uvicorn
    from astra_web.app import create_app
    uvicorn.run(create_app(), host=args.host, port=args.port, workers=1, proxy_headers=args.proxy_headers,
                forwarded_allow_ips='127.0.0.1',
                access_log=False, limit_concurrency=64, timeout_keep_alive=5)
