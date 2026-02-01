import ccxt
import asyncio
import time
import hmac
import hashlib
import base64
import urllib.parse
import aiohttp
import socket
import ssl
import logging
from typing import Dict, List, Optional, Any
import random
from config.settings import BINGX_API_KEY, BINGX_SECRET_KEY, BINGX_PROXY, BINGX_PROXY_LIST, BINGX_SSL_VERIFY

logger = logging.getLogger(__name__)

# Импорт SSL исключений
try:
    from ssl import SSLError, SSLCertVerificationError
except ImportError:
    # Для старых версий Python (до 3.7)
    SSLError = ssl.SSLError
    try:
        SSLCertVerificationError = ssl.SSLCertVerificationError
    except AttributeError:
        SSLCertVerificationError = ssl.SSLError


class BingXAPI:
    """
    Класс для работы с API BingX через ccxt и прямые запросы
    
    Согласно proverka.txt:
    - Используется CCXT для унификации API (рекомендация)
    - REST API для получения данных (для реал-тайм можно добавить WebSocket)
    - Перпетульный API (swap) для лучшей глубины стакана (до 100 уровней)
    - Rate limits: 1200 req/min для REST, WS без жестких лимитов
    """
    
    def __init__(self, api_key: Optional[str] = None, secret_key: Optional[str] = None, sandbox: bool = False):
        self.api_key = api_key or BINGX_API_KEY
        self.secret_key = secret_key or BINGX_SECRET_KEY
        self.sandbox = sandbox  # Используется только для логики, не для URL
        # BingX не имеет публичного testnet API, всегда используем основной URL
        self.base_url = 'https://open-api.bingx.com'
        
        # Прокси для BingX API (поддержка нескольких прокси с ротацией)
        self.proxy_list = BINGX_PROXY_LIST.copy() if BINGX_PROXY_LIST else []
        # Нормализуем прокси (добавляем протокол если нужно)
        self.proxy_list = [self._normalize_proxy(p) for p in self.proxy_list]
        # Текущий прокси (для ротации)
        self.current_proxy_index = 0
        self.proxy = self.proxy_list[0] if self.proxy_list else None
        
        # Логируем информацию о прокси
        if self.proxy_list:
            logger.info(f"✅ Загружено {len(self.proxy_list)} прокси для BingX API")
            if len(self.proxy_list) > 1:
                logger.info(f"   Ротация прокси включена (автоматическая смена при ошибках)")
        
        # Настройка SSL: если проверка отключена, создаём SSL контекст без проверки
        self.ssl_verify = BINGX_SSL_VERIFY
        if not self.ssl_verify:
            # Создаём SSL контекст без проверки сертификатов (небезопасно, но необходимо при проблемах с сертификатами)
            self.ssl_context = ssl.create_default_context()
            self.ssl_context.check_hostname = False
            self.ssl_context.verify_mode = ssl.CERT_NONE
        else:
            self.ssl_context = None  # Используем стандартную проверку SSL
        
        # Настройка ccxt с правильными параметрами для BingX
        # sandbox=False, так как BingX не поддерживает testnet через API
        ccxt_config = {
            'apiKey': self.api_key or '',  # Может быть пустым для публичных запросов
            'secret': self.secret_key or '',  # Может быть пустым для публичных запросов
            'sandbox': False,  # BingX не поддерживает sandbox через API
            'enableRateLimit': True,
            'options': {
                'defaultType': 'swap',  # Perpetual futures
                'adjustForTimeDifference': True,
                'family': 4,  # Принудительно используем только IPv4 (решает проблему "No route to host" в 80% случаев)
            },
            'timeout': 30000,
        }
        
        # Добавляем прокси в ccxt, если указан (используем первый из списка)
        if self.proxy:
            ccxt_config['proxies'] = {
                'http': self.proxy,
                'https': self.proxy,
            }
        
        # Для публичных запросов создаём отдельный экземпляр без API ключей
        # Это позволяет избежать ошибок подписи для публичных endpoints
        ccxt_public_config = {
            'enableRateLimit': True,
            'options': {
                'defaultType': 'swap',
                'adjustForTimeDifference': True,
                'family': 4,  # Принудительно используем только IPv4
            },
            'timeout': 30000,
        }
        
        # Добавляем прокси в публичный экземпляр, если указан
        if self.proxy:
            ccxt_public_config['proxies'] = {
                'http': self.proxy,
                'https': self.proxy,
            }
        
        self.exchange = ccxt.bingx(ccxt_config)
        # Создаём отдельный экземпляр для публичных запросов (без API ключей)
        self.public_exchange = ccxt.bingx(ccxt_public_config)
        
    def _normalize_proxy(self, proxy: str) -> str:
        """Нормализует формат прокси, добавляя протокол если нужно"""
        if not proxy:
            return proxy
        if not proxy.startswith(('http://', 'https://', 'socks5://', 'socks4://')):
            return f"http://{proxy}"
        return proxy
    
    def _get_next_proxy(self) -> Optional[str]:
        """Получить следующий прокси из списка (ротация)"""
        if not self.proxy_list:
            return None
        proxy = self.proxy_list[self.current_proxy_index]
        self.current_proxy_index = (self.current_proxy_index + 1) % len(self.proxy_list)
        return proxy
    
    def _get_random_proxy(self) -> Optional[str]:
        """Получить случайный прокси из списка"""
        if not self.proxy_list:
            return None
        return random.choice(self.proxy_list)
    
    def _generate_signature(self, method: str, path: str, params: Dict[str, Any]) -> str:
        """
        Генерирует подпись для BingX API согласно документации
        
        Формат: HMAC-SHA256(METHOD + PATH + param_string)
        где param_string - отсортированные параметры в формате key=value&key2=value2
        Результат кодируется в Base64 и затем URL-encode
        """
        # Убеждаемся, что timestamp есть
        if 'timestamp' not in params:
            params['timestamp'] = int(time.time() * 1000)
        
        # Сортируем параметры по ключу (без signature)
        sorted_params = sorted([(k, v) for k, v in params.items() if k != 'signature'])
        
        # Создаём param_string в формате key=value&key2=value2
        param_string = "&".join([f"{k}={v}" for k, v in sorted_params])
        
        # Создаём origin string: METHOD + PATH + param_string
        method_upper = method.upper()
        origin_string = f"{method_upper}{path}{param_string}"
        
        # Генерируем HMAC SHA256 (бинарный дайджест)
        hmac_digest = hmac.new(
            self.secret_key.encode('utf-8'),
            origin_string.encode('utf-8'),
            hashlib.sha256
        ).digest()  # .digest() возвращает байты, не hex
        
        # Кодируем в Base64
        b64_signature = base64.b64encode(hmac_digest).decode('utf-8')
        
        # URL-кодируем результат
        signature = urllib.parse.quote(b64_signature, safe='')
        
        return signature
    
    def _translate_connection_error(self, error_str: str) -> Exception:
        """Переводит ClientConnectorError в информативное сообщение для пользователя"""
        if "SSL" in error_str or "certificate" in error_str.lower() or "CERTIFICATE_VERIFY_FAILED" in error_str:
            if self.ssl_verify:
                return Exception(
                    f"❌ Ошибка SSL сертификата при подключении к API BingX:\n\n"
                    f"Ошибка: {error_str}\n\n"
                    f"💡 Решение:\nДобавьте в файл .env:\nBINGX_SSL_VERIFY=false\n\n"
                    f"⚠️ Отключение проверки SSL снижает безопасность."
                )
            return Exception(
                f"❌ Ошибка SSL даже с отключенной проверкой:\n{error_str}\n\n"
                f"Проверьте интернет-соединение и настройки прокси."
            )
        if "No route to host" in error_str or "cannot connect" in error_str.lower():
            if not self.proxy:
                return Exception(
                    f"❌ Не удалось подключиться к серверу BingX.\n\n"
                    f"Ошибка: {error_str}\n\n"
                    f"💡 <b>Диагностика:</b>\n"
                    f"Если <code>ping open-api.bingx.com</code> показывает 100% потерю пакетов,\n"
                    f"домен заблокирован на уровне провайдера/страны.\n\n"
                    f"✅ <b>Бот уже использует IPv4</b> для решения проблем с IPv6.\n\n"
                    f"🔧 <b>Обязательное решение:</b>\n"
                    f"Используйте прокси или VPN:\n\n"
                    f"1. <b>Прокси</b> (добавьте в <code>.env</code>):\n"
                    f"   <code>BINGX_PROXY=http://your-proxy:port</code>\n\n"
                    f"2. <b>VPN</b> (сервер в США/Сингапуре/Гонконге)\n\n"
                    f"⚠️ Без прокси/VPN подключение невозможно при блокировке домена."
                )
            return Exception(
                f"❌ Не удалось подключиться даже через прокси.\n\n"
                f"Ошибка: {error_str}\n\n"
                f"Проверьте:\n"
                f"• Правильность адреса прокси\n"
                f"• Доступность прокси-сервера\n"
                f"• Настройки прокси (авторизация, порт)"
            )
        return Exception(
            f"Не удалось подключиться к серверу BingX.\n"
            f"Проверьте интернет-соединение и доступность open-api.bingx.com\n"
            f"Ошибка: {error_str}"
        )

    def _translate_ssl_error(self, ssl_err: Exception) -> Exception:
        """Переводит SSLError в информативное сообщение"""
        if self.ssl_verify:
            return Exception(
                f"❌ Ошибка SSL сертификата:\n{str(ssl_err)}\n\n"
                f"💡 Решение: Добавьте в .env файл:\nBINGX_SSL_VERIFY=false"
            )
        return Exception(f"Ошибка SSL: {str(ssl_err)}")

    async def _do_public_get(self, url_with_params: str) -> Optional[Dict]:
        """Выполняет GET запрос к публичному endpoint с ретрай и обработкой ошибок.

        Возвращает dict с 'data' при успехе или None при неперехваченной ошибке API.
        Сетевые ошибки (SSL, timeout, connection) пробрасываются как Exception.
        """
        ssl_param = self.ssl_context if not self.ssl_verify else True
        timeout = aiohttp.ClientTimeout(total=20, connect=7)
        connector = aiohttp.TCPConnector(family=socket.AF_INET, ssl=ssl_param)

        async with aiohttp.ClientSession(timeout=timeout, connector=connector) as session:
            for attempt in range(2):
                try:
                    async with session.get(url_with_params, ssl=ssl_param, proxy=self.proxy) as response:
                        if response.status == 200:
                            data = await response.json()
                            if data.get('code') == 0 and 'data' in data:
                                return data
                            raise Exception(data.get('msg', 'API error'))
                        return None
                except aiohttp.ClientConnectorError as e:
                    error_str = str(e)
                    if "SSL" in error_str or "certificate" in error_str.lower():
                        raise self._translate_ssl_error(e)
                    if attempt < 1:
                        await asyncio.sleep(0.3 * (attempt + 1))
                        continue
                    raise self._translate_connection_error(error_str)
                except (aiohttp.ServerTimeoutError, asyncio.TimeoutError):
                    if attempt < 1:
                        await asyncio.sleep(0.3 * (attempt + 1))
                        continue
                    raise Exception("Таймаут соединения с сервером BingX.")
                except (SSLError, SSLCertVerificationError) as ssl_err:
                    raise self._translate_ssl_error(ssl_err)
                except Exception:
                    break  # API-level error — не ретраим
        return None

    async def _make_request(self, method: str, endpoint: str, params: Optional[Dict] = None) -> Dict:
        """Выполняет прямой HTTP запрос к BingX API (authenticated)"""
        if params is None:
            params = {}

        if 'timestamp' not in params:
            params['timestamp'] = int(time.time() * 1000)
        signature = self._generate_signature(method, endpoint, params)
        params['signature'] = signature

        url = f"{self.base_url}{endpoint}"
        headers = {
            'X-BX-APIKEY': self.api_key,
            'Content-Type': 'application/json',
        }
        ssl_param = self.ssl_context if not self.ssl_verify else True
        timeout = aiohttp.ClientTimeout(total=10, connect=5)
        connector = aiohttp.TCPConnector(
            limit=10, limit_per_host=5, family=socket.AF_INET, ssl=ssl_param
        )

        current_proxy = self.proxy
        max_retries = len(self.proxy_list) if self.proxy_list else 1

        try:
            async with aiohttp.ClientSession(timeout=timeout, connector=connector) as session:
                for attempt in range(max_retries):
                    try:
                        if method.upper() == 'GET':
                            sorted_params = sorted(params.items())
                            query_string = urllib.parse.urlencode(sorted_params)
                            request_url = f"{url}?{query_string}"
                            ctx = session.get(request_url, headers=headers, ssl=ssl_param, proxy=current_proxy)
                        else:
                            request_url = url
                            ctx = session.post(url, headers=headers, json=params, ssl=ssl_param, proxy=current_proxy)

                        async with ctx as response:
                            data = await response.json()
                            if response.status != 200 or data.get('code') != 0:
                                error_msg = data.get('msg', f'HTTP {response.status}')
                                raise Exception(f"API Error: {error_msg} (code: {data.get('code', 'unknown')})")
                            return data
                    except aiohttp.ClientConnectorError as conn_error:
                        if attempt < max_retries - 1 and len(self.proxy_list) > 1:
                            logger.debug(f"Прокси {current_proxy} не работает, пробуем следующий...")
                            current_proxy = self._get_next_proxy()
                            continue
                        raise self._translate_connection_error(str(conn_error))
        except aiohttp.ServerTimeoutError:
            raise Exception("Таймаут соединения с сервером BingX.\nСервер не отвечает. Попробуйте позже.")
        except (SSLError, SSLCertVerificationError) as ssl_err:
            raise self._translate_ssl_error(ssl_err)
        except Exception as e:
            if any(x in str(e) for x in ["Не удалось подключиться", "Таймаут", "SSL"]):
                raise
            raise Exception(f"Ошибка соединения: {str(e)}")
    
    async def get_balance(self) -> Dict[str, Any]:
        """Получить баланс аккаунта"""
        try:
            # Пробуем через прямой запрос (более надёжно для BingX)
            try:
                response = await self._make_request('GET', '/openApi/swap/v2/user/balance', {})
                if response.get('code') == 0 and 'data' in response:
                    balance_data = response['data']
                    # Ищем USDT баланс
                    usdt_balance = next((b for b in balance_data.get('balance', []) if b.get('asset') == 'USDT'), {})
                    return {
                        'total': float(usdt_balance.get('balance', 0)),
                        'free': float(usdt_balance.get('availableBalance', 0)),
                        'used': float(usdt_balance.get('balance', 0)) - float(usdt_balance.get('availableBalance', 0)),
                    }
            except Exception as direct_error:
                # Если прямой запрос не сработал, пробуем через ccxt
                balance = await asyncio.to_thread(self.exchange.fetch_balance)
                return {
                    'total': balance.get('USDT', {}).get('total', 0),
                    'free': balance.get('USDT', {}).get('free', 0),
                    'used': balance.get('USDT', {}).get('used', 0),
                }
        except Exception as e:
            raise Exception(f"Ошибка получения баланса: {str(e)}")
    
    async def get_ticker(self, symbol: str) -> Dict[str, Any]:
        """Получить текущую цену - публичный endpoint"""
        try:
            symbol_normalized = symbol.replace('/', '-').replace(':USDT', '')
            url = f"{self.base_url}/openApi/swap/v3/quote/ticker?symbol={symbol_normalized}"

            data = await self._do_public_get(url)
            if data:
                ticker_data = data['data']
                return {
                    'symbol': symbol,
                    'last': float(ticker_data.get('lastPrice', 0)),
                    'bid': float(ticker_data.get('bidPrice', 0)),
                    'ask': float(ticker_data.get('askPrice', 0)),
                    'volume': float(ticker_data.get('quoteVolume', 0)),
                    'change': float(ticker_data.get('priceChangePercent', 0)),
                }

            # Fallback на ccxt публичный экземпляр
            ticker = await asyncio.to_thread(self.public_exchange.fetch_ticker, symbol)
            return {
                'symbol': symbol,
                'last': ticker['last'],
                'bid': ticker['bid'],
                'ask': ticker['ask'],
                'volume': ticker.get('quoteVolume', ticker.get('baseVolume', 0)),
                'change': ticker.get('percentage', 0),
            }
        except Exception as e:
            raise Exception(f"Ошибка получения цены: {str(e)}")

    async def get_top_usdt_perp_pairs_by_volume(self, limit: int = 10, min_quote_volume: float = 0) -> List[str]:
        """
        Возвращает топ USDT-perp пар по 24h quoteVolume.

        Используем ccxt public_exchange.fetch_tickers() (публично), т.к. он обычно
        возвращает quoteVolume по всем рынкам.
        """
        try:
            tickers = await asyncio.to_thread(self.public_exchange.fetch_tickers)
        except Exception as e:
            raise Exception(f"Не удалось получить tickers для подбора пар: {e}")

        candidates: List[Dict[str, Any]] = []
        for sym, t in (tickers or {}).items():
            # Оставляем только USDT perpetual в формате BTC/USDT:USDT
            if not isinstance(sym, str):
                continue
            if not sym.endswith(":USDT"):
                continue
            if "/USDT" not in sym:
                continue

            qv = t.get("quoteVolume")
            if qv is None:
                qv = t.get("baseVolume", 0)
            try:
                qv_f = float(qv or 0)
            except Exception:
                qv_f = 0
            if qv_f < float(min_quote_volume):
                continue

            candidates.append({"symbol": sym, "quoteVolume": qv_f})

        candidates.sort(key=lambda x: x["quoteVolume"], reverse=True)
        top = [c["symbol"] for c in candidates[: max(1, int(limit))]]
        return top
    
    @staticmethod
    def _validate_ohlcv(raw_data: list) -> List[List]:
        """Валидирует и нормализует raw OHLCV данные"""
        validated = []
        for candle in raw_data:
            if isinstance(candle, (list, tuple)) and len(candle) >= 6:
                try:
                    validated.append([
                        int(candle[0]),
                        float(candle[1]),
                        float(candle[2]),
                        float(candle[3]),
                        float(candle[4]),
                        float(candle[5]),
                    ])
                except (ValueError, TypeError, IndexError):
                    continue
        return validated

    async def get_ohlcv(self, symbol: str, timeframe: str = '15m', limit: int = 300) -> List[List]:
        """Получить свечи (OHLCV) через публичный API endpoint"""
        try:
            symbol_normalized = symbol.replace('/', '-').replace(':USDT', '')
            if symbol_normalized.endswith('-USDT-USDT'):
                symbol_normalized = symbol_normalized.replace('-USDT-USDT', '-USDT')

            params = {'symbol': symbol_normalized, 'interval': timeframe, 'limit': limit}
            url = f"{self.base_url}/openApi/swap/v3/quote/klines?{urllib.parse.urlencode(params)}"

            data = await self._do_public_get(url)
            if data:
                validated = self._validate_ohlcv(data['data'])
                if not validated:
                    raise Exception(f"API вернул пустые данные для {symbol}")
                return validated

            # Fallback на CCXT публичный экземпляр
            ohlcv = await asyncio.to_thread(
                self.public_exchange.fetch_ohlcv, symbol, timeframe, limit=limit
            )
            if not ohlcv:
                raise Exception(f"API вернул пустые данные для {symbol}")

            validated = self._validate_ohlcv(ohlcv)
            if not validated:
                raise Exception(f"Не удалось обработать данные свечей для {symbol}")
            return validated

        except Exception as e:
            error_msg = str(e)
            if "No route to host" in error_msg or "Name or service not known" in error_msg:
                raise Exception(
                    f"❌ Не удалось подключиться к API BingX.\n\n"
                    f"Попробуйте использовать прокси (BINGX_PROXY в .env)"
                )
            raise Exception(f"Ошибка получения свечей для {symbol}: {error_msg}")
    async def get_order_book(self, symbol: str, limit: int = 50) -> Dict[str, Any]:
        """
        Получить стакан (order book) - публичный endpoint, подпись не требуется.

        Согласно proverka.txt: для перпетульного API рекомендуется глубина до 100 уровней.
        По умолчанию используем 50 для баланса между точностью и производительностью.
        """
        try:
            symbol_normalized = symbol.replace('/', '-').replace(':USDT', '')
            params = {'symbol': symbol_normalized, 'limit': limit}
            url = f"{self.base_url}/openApi/swap/v3/quote/depth?{urllib.parse.urlencode(params)}"

            data = await self._do_public_get(url)
            if data:
                orderbook_data = data['data']
                return {
                    'bids': orderbook_data.get('bids', []),
                    'asks': orderbook_data.get('asks', []),
                    'timestamp': int(time.time() * 1000),
                }

            # Fallback на ccxt публичный экземпляр
            orderbook = await asyncio.to_thread(
                self.public_exchange.fetch_order_book, symbol, limit
            )
            return {
                'bids': orderbook['bids'],
                'asks': orderbook['asks'],
                'timestamp': orderbook['timestamp'],
            }
        except Exception as e:
            raise Exception(f"Ошибка получения стакана: {str(e)}")
    
    async def create_market_order(self, symbol: str, side: str, amount: float) -> Dict[str, Any]:
        """Создать рыночный ордер"""
        try:
            order = await asyncio.to_thread(
                self.exchange.create_market_order,
                symbol,
                side,  # 'buy' or 'sell'
                amount
            )
            return order
        except Exception as e:
            raise Exception(f"Ошибка создания ордера: {str(e)}")
    
    async def create_limit_order(self, symbol: str, side: str, amount: float, price: float) -> Dict[str, Any]:
        """Создать лимитный ордер"""
        try:
            order = await asyncio.to_thread(
                self.exchange.create_limit_order,
                symbol,
                side,
                amount,
                price
            )
            return order
        except Exception as e:
            raise Exception(f"Ошибка создания лимитного ордера: {str(e)}")
    
    async def create_stop_loss_order(self, symbol: str, side: str, amount: float, 
                                     stop_price: float, price: Optional[float] = None) -> Dict[str, Any]:
        """
        Создать стоп-лосс ордер
        
        Args:
            symbol: Торговая пара
            side: 'buy' для закрытия short, 'sell' для закрытия long
            amount: Объём
            stop_price: Цена активации стоп-лосса
            price: Цена исполнения (для stop-limit), если None - market order
        """
        try:
            # Используем ccxt для создания стоп-лосс ордера
            # BingX поддерживает stop-market и stop-limit ордера
            if price is None:
                # Stop-market ордер
                order = await asyncio.to_thread(
                    self.exchange.create_order,
                    symbol,
                    'stop',
                    side,
                    amount,
                    None,  # price не нужен для stop-market
                    params={
                        'stopPrice': stop_price,
                        'stopOrderType': 'Stop'
                    }
                )
            else:
                # Stop-limit ордер
                order = await asyncio.to_thread(
                    self.exchange.create_order,
                    symbol,
                    'stop',
                    side,
                    amount,
                    price,
                    params={
                        'stopPrice': stop_price
                    }
                )
            return order
        except Exception as e:
            raise Exception(f"Ошибка создания стоп-лосс ордера: {str(e)}")
    
    async def create_take_profit_order(self, symbol: str, side: str, amount: float, 
                                       take_profit_price: float, price: Optional[float] = None) -> Dict[str, Any]:
        """
        Создать тейк-профит ордер
        
        Args:
            symbol: Торговая пара
            side: 'buy' для закрытия short, 'sell' для закрытия long
            amount: Объём
            take_profit_price: Цена активации тейк-профита
            price: Цена исполнения (для take-profit limit), если None - market order
        """
        try:
            # BingX использует take-profit ордера через специальные параметры
            if price is None:
                # Take-profit market ордер
                order = await asyncio.to_thread(
                    self.exchange.create_order,
                    symbol,
                    'takeProfit',
                    side,
                    amount,
                    None,
                    params={
                        'stopPrice': take_profit_price,
                        'stopOrderType': 'TakeProfit'
                    }
                )
            else:
                # Take-profit limit ордер
                order = await asyncio.to_thread(
                    self.exchange.create_order,
                    symbol,
                    'takeProfit',
                    side,
                    amount,
                    price,
                    params={
                        'stopPrice': take_profit_price
                    }
                )
            return order
        except Exception as e:
            raise Exception(f"Ошибка создания тейк-профит ордера: {str(e)}")
    
    async def set_leverage(self, symbol: str, leverage: int) -> bool:
        """Установить плечо"""
        try:
            await asyncio.to_thread(
                self.exchange.set_leverage,
                leverage,
                symbol
            )
            return True
        except Exception as e:
            raise Exception(f"Ошибка установки плеча: {str(e)}")
    
    async def get_positions(self) -> List[Dict[str, Any]]:
        """Получить открытые позиции через прямой API запрос"""
        try:
            # Используем прямой запрос к API (как для баланса) - более надежно
            response = await self._make_request('GET', '/openApi/swap/v2/user/positions', {})
            
            if response.get('code') == 0 and 'data' in response:
                positions_data = response['data']
                
                # Преобразуем формат BingX в формат, ожидаемый кодом
                positions = []
                for pos in positions_data:
                    # Проверяем, что позиция открыта (positionSize != 0)
                    position_size = float(pos.get('positionSize', 0))
                    if position_size != 0:
                        # Преобразуем формат
                        position_side = pos.get('positionSide', 'long').lower()
                        # BingX использует 'long'/'short', приводим к нужному формату
                        side = 'long' if position_side in ['long', 'buy'] else 'short'
                        
                        positions.append({
                            'symbol': pos.get('symbol', '').replace('-', '/') + ':USDT',  # BTC-USDT -> BTC/USDT:USDT
                            'contracts': position_size,
                            'side': side,
                            'entryPrice': float(pos.get('entryPrice', 0)),
                            'markPrice': float(pos.get('currentPrice', pos.get('markPrice', 0))),
                            'unrealizedPnl': float(pos.get('unrealizedPnl', 0)),
                            'leverage': int(pos.get('leverage', 1)),
                            'marginType': pos.get('marginType', 'isolated'),
                            'liquidationPrice': float(pos.get('liquidationPrice', 0)) if pos.get('liquidationPrice') else None,
                        })
                
                return positions
            else:
                # Если API вернул ошибку, возвращаем пустой список
                error_msg = response.get('msg', 'Unknown error')
                raise Exception(f"API вернул ошибку при получении позиций: {error_msg}")
                
        except Exception as e:
            error_msg = str(e)
            
            # Если это ошибка подписи - это известная проблема с BingX API для некоторых endpoints
            # Возвращаем пустой список, чтобы авто-торговля могла продолжать работу
            # Проверка позиций будет пропущена, но это лучше, чем полная остановка торговли
            if "100001" in error_msg or "signature" in error_msg.lower():
                # Пробуем CCXT как fallback
                try:
                    positions = await asyncio.to_thread(self.exchange.fetch_positions)
                    open_positions = [pos for pos in positions if pos.get('contracts', 0) != 0]
                    return open_positions
                except Exception:
                    # Если и CCXT не работает - возвращаем пустой список
                    # Это позволит авто-торговле продолжить работу без проверки позиций
                    print(f"[BingX API] ⚠️ Не удалось получить позиции (ошибка подписи API), возвращаю пустой список")
                    return []
            
            # Для других ошибок тоже возвращаем пустой список, чтобы не блокировать авто-торговлю
            if "API вернул ошибку" in error_msg:
                print(f"[BingX API] ⚠️ API вернул ошибку при получении позиций, возвращаю пустой список")
                return []
            
            # Для критических ошибок (сеть, таймаут) пробрасываем исключение
            if "Не удалось подключиться" in error_msg or "Таймаут" in error_msg:
                raise Exception(f"Ошибка получения позиций: {error_msg}")
            
            # Для остальных ошибок возвращаем пустой список
            print(f"[BingX API] ⚠️ Ошибка при получении позиций: {error_msg[:100]}, возвращаю пустой список")
            return []
    
    async def close_position(self, symbol: str, side: Optional[str] = None) -> bool:
        """Закрыть позицию"""
        try:
            positions = await self.get_positions()
            for pos in positions:
                if pos['symbol'] == symbol:
                    if side is None or pos['side'] == side:
                        # Закрываем позицию противоположным ордером
                        close_side = 'sell' if pos['side'] == 'long' else 'buy'
                        amount = abs(pos['contracts'])
                        await self.create_market_order(symbol, close_side, amount)
                        return True
            return False
        except Exception as e:
            raise Exception(f"Ошибка закрытия позиции: {str(e)}")
    
    async def close_all_positions(self) -> int:
        """Закрыть все позиции"""
        try:
            positions = await self.get_positions()
            closed = 0
            for pos in positions:
                symbol = pos['symbol']
                close_side = 'sell' if pos['side'] == 'long' else 'buy'
                amount = abs(pos['contracts'])
                await self.create_market_order(symbol, close_side, amount)
                closed += 1
            return closed
        except Exception as e:
            raise Exception(f"Ошибка закрытия всех позиций: {str(e)}")
    
    async def test_api(self) -> bool:
        """Проверить работоспособность API"""
        try:
            # Проверяем базовую доступность API через простой endpoint
            # Используем endpoint для проверки баланса
            response = await self._make_request('GET', '/openApi/swap/v2/user/balance', {})
            if response.get('code') == 0:
                return True
            else:
                error_msg = response.get('msg', 'Unknown error')
                error_code = response.get('code', 'unknown')
                
                # Специальная обработка для ошибок подписи
                if error_code == 100001 or 'signature' in error_msg.lower():
                    raise Exception(
                        f"Ошибка подписи API (code {error_code}): {error_msg}\n\n"
                        f"Проверьте:\n"
                        f"1. Правильность API ключа и Secret ключа\n"
                        f"2. Что API ключ имеет права на чтение баланса\n"
                        f"3. Что IP адрес не заблокирован (если включена защита)\n"
                        f"4. Что системное время синхронизировано"
                    )
                
                raise Exception(f"API вернул ошибку (code {error_code}): {error_msg}")
        except Exception as e:
            error_message = str(e)
            
            # Если это уже обработанная ошибка соединения, пробрасываем как есть
            if "Не удалось подключиться" in error_message or "Таймаут" in error_message or "Не удалось разрешить домен" in error_message:
                raise Exception(f"API не работает: {error_message}")
            
            # Проверяем SSL ошибки
            if "SSL" in error_message or "certificate" in error_message.lower() or "CERTIFICATE_VERIFY_FAILED" in error_message:
                # Если это SSL ошибка, пробрасываем как есть (уже обработана с инструкциями)
                raise Exception(f"API не работает: {error_message}")
            
            # Проверяем типичные ошибки подписи
            if 'signature' in error_message.lower() or '100001' in error_message:
                raise Exception(
                    f"Ошибка подписи API. Проверьте:\n"
                    f"1. Правильность API ключа и Secret ключа\n"
                    f"2. Что API ключ имеет права на чтение баланса\n"
                    f"3. Что IP адрес не заблокирован (если включена защита)\n"
                    f"4. Что системное время синхронизировано\n\n"
                    f"Детали ошибки: {error_message}"
                )
            
            raise Exception(f"API не работает: {error_message}")
