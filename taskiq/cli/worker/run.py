import asyncio
import inspect
import logging
import os
import signal
import sys
import time
from concurrent.futures import Executor, ProcessPoolExecutor, ThreadPoolExecutor
from multiprocessing import current_process, get_start_method, set_start_method
from sys import platform
from typing import Any

from taskiq.abc.broker import AsyncBroker
from taskiq.cli.utils import import_object, import_tasks
from taskiq.cli.worker.args import WorkerArgs
from taskiq.cli.worker.health_checker import MiddlewareHealthDetail
from taskiq.cli.worker.process_manager import ProcessManager
from taskiq.receiver import Receiver

try:
    import uvloop
except ImportError:
    uvloop = None  # type: ignore


try:
    from watchdog.observers import Observer
except ImportError:
    Observer = None  # type: ignore


logger = logging.getLogger("taskiq.worker")


async def collect_middleware_health(
    broker: AsyncBroker,
) -> dict[str, MiddlewareHealthDetail]:
    """
    Query all middleware for health status.

    Middleware that raise NotImplementedError opt-out (default behavior).
    Middleware that raise exceptions are marked as unhealthy.

    :param broker: Broker instance with middlewares.
    :returns: Dictionary of middleware health results.
    """
    middleware_health: dict[str, MiddlewareHealthDetail] = {}

    for middleware in broker.middlewares:
        middleware_name = middleware.__class__.__name__
        try:
            health_result = middleware.health()
            if health_result is None:
                continue
            result = (
                await health_result
                if asyncio.iscoroutine(health_result)
                else health_result
            )
            if result is None:
                continue
            middleware_health[middleware_name] = MiddlewareHealthDetail(
                middleware_name=middleware_name,
                is_healthy=result.is_healthy,
                data=result.data,
            )
        except NotImplementedError:
            continue
        except Exception as e:
            logger.error(
                "Middleware %s health check failed: %s",
                middleware_name,
                e,
                exc_info=True,
            )
            middleware_health[middleware_name] = MiddlewareHealthDetail(
                middleware_name=middleware_name,
                is_healthy=False,
                data={"error": str(e)},
            )

    return middleware_health


async def send_heartbeat(
    health_pipe: Any,
    broker: AsyncBroker,
) -> None:
    """
    Send periodic health heartbeats to main process.

    :param health_pipe: Queue for sending heartbeats.
    :param broker: Broker instance (may have connection checking).
    """
    logger.debug(
        "Heartbeat sender started for %s",
        current_process().name,
    )
    heartbeat_count = 0
    while True:
        try:
            # Check broker connection status
            # Note: Different brokers may implement this differently
            broker_connected = True  # Default to True if no check available

            logger.debug(
                "Preparing to send heartbeat #%d from %s",
                heartbeat_count + 1,
                current_process().name,
            )

            middleware_health = await collect_middleware_health(broker)

            # Queue.put() is synchronous, no await needed
            health_pipe.put(
                {
                    "worker_id": current_process().name,
                    "timestamp": time.time(),
                    "broker_connected": broker_connected,
                    "middleware_health": middleware_health,
                },
            )

            heartbeat_count += 1
            logger.debug(
                "Sent heartbeat #%d from %s at %s",
                heartbeat_count,
                current_process().name,
                time.time(),
            )
        except (ConnectionError, OSError) as e:
            # Queue closed, stop sending heartbeats
            logger.error(
                "Health queue error for %s (stopping heartbeats): %s",
                current_process().name,
                e,
            )
            break
        except Exception as e:
            # Unexpected error - log but continue
            logger.error(
                "Unexpected heartbeat error for %s: %s",
                current_process().name,
                e,
                exc_info=True,
            )
        await asyncio.sleep(5)  # Send every 5 seconds


async def run_with_heartbeat(
    health_pipe: Any,
    broker: AsyncBroker,
    receiver: Receiver,
    shutdown_event: asyncio.Event,
) -> None:
    """
    Run receiver and heartbeat task concurrently.

    :param health_pipe: Queue for sending heartbeats.
    :param broker: Broker instance.
    :param receiver: Receiver instance.
    :param shutdown_event: Shutdown event.
    """
    heartbeat_task = asyncio.create_task(
        send_heartbeat(health_pipe, broker),
    )
    receiver_task = asyncio.create_task(receiver.listen(shutdown_event))
    _, pending = await asyncio.wait(
        [heartbeat_task, receiver_task],
        return_when=asyncio.FIRST_COMPLETED,
    )
    # Cancel pending tasks
    for task in pending:
        task.cancel()


async def shutdown_broker(broker: AsyncBroker, timeout: float) -> None:
    """
    This function used to shutdown broker.

    Broker can throw errors during shutdown,
    or it may return some value.

    We need to handle such situations.

    :param broker: current broker.
    :param timeout: maximum amount of time to shutdown the broker.
    """
    logger.info("Shutting down the broker.")
    try:
        ret_val = await asyncio.wait_for(broker.shutdown(), timeout)  # type: ignore
        if ret_val is not None:
            logger.info("Broker has returned value on shutdown: '%s'", str(ret_val))
    except asyncio.TimeoutError:
        logger.warning("Broker.shutdown cannot be completed in %s seconds.", timeout)
    except Exception as exc:
        logger.warning(
            "Exception found while shutting down broker: %s",
            exc,
            exc_info=True,
        )


def get_receiver_type(args: WorkerArgs) -> type[Receiver]:
    """
    Import Receiver from args.

    :param args: CLI arguments.
    :raises ValueError: if receiver is not a Receiver type.
    :return: Receiver type.
    """
    receiver_type = import_object(args.receiver, app_dir=args.app_dir)
    if not (isinstance(receiver_type, type) and issubclass(receiver_type, Receiver)):
        raise ValueError("Unknown receiver type. Please use Receiver class.")
    return receiver_type


def _setup_logging(args: WorkerArgs) -> None:
    """Configure logging for spawn method workers."""
    if args.configure_logging and get_start_method() == "spawn":
        logging.basicConfig(
            level=args.log_level,
            format=args.log_format,
        )


def _setup_broker(args: WorkerArgs) -> AsyncBroker:
    """
    Setup and return broker instance.

    :param args: CLI arguments.
    :returns: Configured broker instance.
    :raises ValueError: if broker is not valid.
    """
    if isinstance(args.broker, AsyncBroker):
        broker = args.broker
    else:
        broker = import_object(args.broker, app_dir=args.app_dir)
        if inspect.isfunction(broker):
            broker = broker()
        if not isinstance(broker, AsyncBroker):
            raise ValueError(
                "Unknown broker type. Please use AsyncBroker instance "
                "or pass broker factory function that returns an AsyncBroker instance.",
            )

    broker.is_worker_process = True
    import_tasks(args.modules, args.tasks_pattern, args.fs_discover)
    return broker


def _setup_event_loop() -> asyncio.AbstractEventLoop:
    """Create and set up event loop."""
    if uvloop is not None:
        logger.debug("UVLOOP found. Using it as async runner")
        loop = uvloop.new_event_loop()  # type: ignore
    else:
        loop = asyncio.new_event_loop()

    asyncio.set_event_loop(loop)
    return loop


def _setup_receiver(args: WorkerArgs, broker: AsyncBroker) -> tuple[Receiver, Executor]:
    """
    Setup receiver and executor.

    :param args: CLI arguments.
    :param broker: Broker instance.
    :returns: Tuple of (receiver, executor).
    """
    receiver_type = get_receiver_type(args)
    receiver_kwargs = dict(args.receiver_arg)

    executor: Executor
    if args.use_process_pool:
        executor = ProcessPoolExecutor(max_workers=args.max_process_pool_processes)
    else:
        executor = ThreadPoolExecutor(max_workers=args.max_threadpool_threads)

    receiver = receiver_type(
        broker=broker,
        executor=executor,
        validate_params=not args.no_parse,
        max_async_tasks=args.max_async_tasks,
        max_prefetch=args.max_prefetch,
        propagate_exceptions=not args.no_propagate_errors,
        ack_type=args.ack_type,
        max_tasks_to_execute=args.max_tasks_per_child,
        wait_tasks_timeout=args.wait_tasks_timeout,
        **receiver_kwargs,  # type: ignore
    )

    return receiver, executor


def start_listen(args: WorkerArgs, health_pipe: Any | None = None) -> None:
    """
    This function starts actual listening process.

    It imports broker and all tasks.
    Since tasks auto registers themselves in a broker,
    we don't need to do anything else other than importing.


    :param args: CLI arguments.
    :param health_pipe: Pipe for sending health heartbeats to main process.
    :raises ValueError: if broker is not an AsyncBroker instance.
    :raises ValueError: if receiver is not a Receiver type.
    """
    _setup_logging(args)

    shutdown_event = asyncio.Event()
    hardkill_counter = 0

    def interrupt_handler(signum: int, _frame: Any) -> None:
        """
        Signal handler.

        This handler checks if process is already
        terminating and if it's true, it does nothing.

        :param signum: received signal number.
        :param _frame: current execution frame.
        :raises KeyboardInterrupt: if termination hasn't begun.
        """
        logger.debug(f"Got signal {signum}.")
        nonlocal shutdown_event
        nonlocal hardkill_counter
        # Soft kill is a signal to start shutdown.
        shutdown_event.set()
        # Hard kill is a signal that we should stop
        # everything immediately.
        if hardkill_counter > args.hardkill_count:
            logger.warning("Hard kill. Exiting.")
            raise KeyboardInterrupt
        hardkill_counter += 1

    signal.signal(signal.SIGINT, interrupt_handler)
    signal.signal(signal.SIGTERM, interrupt_handler)
    if sys.platform != "win32":
        signal.signal(signal.SIGHUP, interrupt_handler)

    loop = _setup_event_loop()
    broker = _setup_broker(args)

    executor: Executor | None = None
    try:
        logger.debug("Initialize receiver.")
        receiver, executor = _setup_receiver(args, broker)

        # Start heartbeat sender if health queue is provided
        if health_pipe:
            logger.debug(
                "Health queue provided for %s, starting heartbeat sender",
                current_process().name,
            )
            loop.run_until_complete(
                run_with_heartbeat(
                    health_pipe,
                    broker,
                    receiver,
                    shutdown_event,
                ),
            )
        else:
            logger.info("No health queue provided for %s", current_process().name)
            loop.run_until_complete(receiver.listen(shutdown_event))
    finally:
        if executor:
            executor.shutdown(wait=True)
        loop.run_until_complete(shutdown_broker(broker, args.shutdown_timeout))


def run_worker(args: WorkerArgs) -> int | None:
    """
    This function starts worker processes.

    It just creates multiple child processes
    and joins them all.

    :param args: CLI arguments.

    :raises ValueError: if reload flag is used, but dependencies are not installed.
    :returns: Optional status code.
    """
    if platform == "darwin":
        set_start_method("spawn")
    if args.configure_logging:
        logging.basicConfig(
            level=args.log_level,
            format=args.log_format,
        )
    logging.getLogger("taskiq").setLevel(level=args.log_level)
    logging.getLogger("watchdog.observers.inotify_buffer").setLevel(level=logging.INFO)
    logger.info("Pid of a main process: %s", str(os.getpid()))
    logger.info("Starting %s worker processes.", args.workers)

    observer = None

    if args.reload and Observer is None:
        raise ValueError("To use '--reload' flag, please install 'taskiq[reload]'.")

    if Observer is not None and args.reload:
        observer = Observer()
        observer.start()
        args.workers = 1
        logging.warning(
            "Reload on change enabled. Number of worker processes set to 1.",
        )

    manager = ProcessManager(args=args, observer=observer, worker_function=start_listen)

    status = manager.start()

    if observer is not None and observer.is_alive():
        if args.reload:
            logger.info("Stopping watching files.")
        observer.stop()

    return status
