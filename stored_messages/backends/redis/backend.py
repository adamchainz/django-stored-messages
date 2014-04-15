from __future__ import unicode_literals

from django.utils import timezone
from django.utils.encoding import force_text
from django.core.serializers.json import DjangoJSONEncoder

import json
from collections import namedtuple
import hashlib

from ..exceptions import MessageTypeNotSupported, MessageDoesNotExist
from ..base import StoredMessagesBackend
from ...settings import stored_messages_settings

try:
    # Let django project bootstrap anyway when not using this backend
    import redis
except ImportError:
    pass


Message = namedtuple('Message', ['id', 'message', 'level', 'tags', 'date'])


class RedisBackend(StoredMessagesBackend):
    """

    """
    def __init__(self):
        self.client = redis.StrictRedis.from_url(stored_messages_settings.REDIS_URL)

    def _flush(self):
        self.client.flushdb()

    def _toJSON(self, msg_instance):
        """
        Dump a Message instance into a JSON string
        """
        return json.dumps(msg_instance._asdict(), cls=DjangoJSONEncoder)

    def _fromJSON(self, json_msg):
        """
        Return a Message instance built from data contained in a JSON string
        """
        return Message(**json.loads(force_text(json_msg)))

    def _store(self, key_tpl, users, msg_instance):
        """
        boilerplate
        """
        if not self.can_handle(msg_instance):
            raise MessageTypeNotSupported()

        for user in users:
            self.client.rpush(key_tpl % user.pk, self._toJSON(msg_instance))

    def _list(self, key_tpl, user):
        """
        boilerplate
        """
        ret = []
        for msg_json in self.client.lrange(key_tpl % user.pk, 0, -1):
            ret.append(self._fromJSON(msg_json))
        return ret

    def create_message(self, level, msg_text, extra_tags=''):
        """
        Message instances are namedtuples of type `Message`.
        The date field is already serialized in datetime.isoformat ECMA-262 format
        """
        now = timezone.now()
        r = now.isoformat()
        if now.microsecond:
            r = r[:23] + r[26:]
        if r.endswith('+00:00'):
            r = r[:-6] + 'Z'

        fingerprint = r + msg_text

        msg_id = hashlib.sha256(fingerprint.encode('ascii', 'ignore')).hexdigest()
        return Message(id=msg_id, message=msg_text, level=level, tags=extra_tags, date=r)

    def inbox_list(self, user):
        if user.is_anonymous():
            return []
        return self._list('user:%d:notifications', user)

    def inbox_purge(self, user):
        if user.is_authenticated():
            self.client.delete('user:%d:notifications' % user.pk)

    def inbox_store(self, users, msg_instance):
        self._store('user:%d:notifications', users, msg_instance)

    def inbox_delete(self, user, msg_id):
        for m in self._list('user:%d:notifications', user):
            if m.id == msg_id:
                return self.client.lrem('user:%d:notifications' % user.pk, 0, json.dumps(m._asdict()))
        raise MessageDoesNotExist("Message with id %s does not exist" % msg_id)

    def inbox_get(self, user, msg_id):
        for m in self._list('user:%d:notifications', user):
            if m.id == msg_id:
                return m
        raise MessageDoesNotExist("Message with id %s does not exist" % msg_id)

    def archive_store(self, users, msg_instance):
        self._store('user:%d:archive', users, msg_instance)

    def archive_list(self, user):
        return self._list('user:%d:archive', user)

    def can_handle(self, msg_instance):
        return isinstance(msg_instance, Message)
