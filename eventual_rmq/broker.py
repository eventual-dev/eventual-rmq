from typing import AsyncIterable, AsyncGenerator, Optional, Callable, Any

import aio_pika
import orjson
from anyio.streams.memory import MemoryObjectReceiveStream, MemoryObjectSendStream

from eventual.dispatch.abc import Message, MessageBroker, EventBody, EventStore


class RmqMessage(Message):
    def __init__(self, message: aio_pika.IncomingMessage):
        self._body = orjson.loads(message.body)
        self._message = message

    @property
    def event_body(self) -> EventBody:
        return self._body

    def acknowledge(self):
        self._message.ack()


class RmqMessageBroker(MessageBroker):
    def __init__(
        self,
        amqp_dsn: str,
        amqp_exchange: str,
        amqp_queue: str,
        routing_key_from_subject: Optional[Callable[[str], str]] = None,
    ):
        self.amqp_dsn = amqp_dsn
        self.amqp_exchange = amqp_exchange
        self.amqp_queue = amqp_queue

        def default_routing_key_from_subject(subject: str) -> str:
            return f"{self.amqp_queue}.{subject}"

        if routing_key_from_subject is None:
            routing_key_from_subject = default_routing_key_from_subject

        self.routing_key_from_subject = routing_key_from_subject

    async def _message_stream(self, connection) -> AsyncGenerator[RmqMessage, None]:
        channel: aio_pika.Channel = await connection.channel()
        async with channel:
            exchange = await channel.declare_exchange(
                self.amqp_exchange, aio_pika.ExchangeType.FANOUT
            )
            queue: aio_pika.Queue = await channel.declare_queue(
                self.amqp_queue, durable=True
            )
            await queue.bind(exchange)

            async with queue.iterator() as queue_iter:
                async for message in queue_iter:
                    yield RmqMessage(message)

    async def message_receive_stream(self) -> AsyncIterable[RmqMessage]:
        connection: aio_pika.RobustConnection = await aio_pika.connect_robust(
            self.amqp_dsn
        )

        async with connection:
            channel: aio_pika.Channel = await connection.channel()
            async with channel:
                exchange = await channel.declare_exchange(
                    self.amqp_exchange, aio_pika.ExchangeType.FANOUT
                )
                queue: aio_pika.Queue = await channel.declare_queue(
                    self.amqp_queue, durable=True
                )
                await queue.bind(exchange)

                async with queue.iterator() as queue_iter:
                    async for message in queue_iter:
                        yield RmqMessage(message)

    async def send_event_body_stream(
        self,
        event_body_stream: MemoryObjectReceiveStream[EventBody],
        confirmation_send_stream: MemoryObjectSendStream[EventBody],
    ):
        connection: aio_pika.RobustConnection = await aio_pika.connect_robust(
            self.amqp_dsn
        )

        async with connection:
            channel: aio_pika.Channel = await connection.channel(
                publisher_confirms=True
            )
            exchange = await channel.declare_exchange(
                self.amqp_exchange, aio_pika.ExchangeType.FANOUT
            )
            async with confirmation_send_stream:
                async with event_body_stream:
                    async for event_body in event_body_stream:
                        subject = event_body["_subject"]
                        await exchange.publish(
                            aio_pika.Message(
                                body=orjson.dumps(event_body),
                                delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
                            ),
                            routing_key=self.routing_key_from_subject(subject),
                        )
                        await confirmation_send_stream.send(event_body)
                        print("RMQ IT")
                    print("RMQ")
