# Copyright 2016 Joel Dunham
#
#  Licensed under the Apache License, Version 2.0 (the "License");
#  you may not use this file except in compliance with the License.
#  You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
#  Unless required by applicable law or agreed to in writing, software
#  distributed under the License is distributed on an "AS IS" BASIS,
#  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#  See the License for the specific language governing permissions and
#  limitations under the License.

import logging
import os
import codecs
import simplejson as json
from nose.tools import nottest
from onlinelinguisticdatabase.tests import TestController, url
import onlinelinguisticdatabase.model as model
from onlinelinguisticdatabase.model import Phonology
from onlinelinguisticdatabase.model.meta import Session
import onlinelinguisticdatabase.lib.helpers as h

log = logging.getLogger(__name__)

class TestPhonologybackupsController(TestController):

    def __init__(self, *args, **kwargs):
        TestController.__init__(self, *args, **kwargs)
        self.test_phonology_script = h.normalize(
            codecs.open(self.test_phonology_script_path, 'r', 'utf8').read())

    def tearDown(self):
        TestController.tearDown(self, dirs_to_destroy=['phonology'])

    @nottest
    def test_index(self):
        """Tests that ``GET /phonologybackups`` behaves correctly.
        """

        # Define some extra_environs
        view = {'test.authentication.role': u'viewer', 'test.application_settings': True}
        contrib = {'test.authentication.role': u'contributor', 'test.application_settings': True}
        admin = {'test.authentication.role': u'administrator', 'test.application_settings': True}

        # Create a phonology.
        params = self.phonology_create_params.copy()
        params.update({
            'name': u'Phonology',
            'description': u'Covers a lot of the data.',
            'script': self.test_phonology_script
        })
        params = json.dumps(params)
        response = self.app.post(url('phonologies'), params, self.json_headers,
                                 self.extra_environ_admin)
        resp = json.loads(response.body)
        phonology_count = Session.query(Phonology).count()
        phonology_dir = os.path.join(self.phonologies_path, 'phonology_%d' % resp['id'])
        phonology_dir_contents = os.listdir(phonology_dir)
        phonology_id = resp['id']
        assert phonology_count == 1
        assert resp['name'] == u'Phonology'
        assert resp['description'] == u'Covers a lot of the data.'
        assert 'phonology.script' in phonology_dir_contents
        assert response.content_type == 'application/json'
        assert resp['script'] == self.test_phonology_script

        # Update the phonology as the admin to create a phonology backup.
        params = self.phonology_create_params.copy()
        params.update({
            'name': u'Phonology Renamed',
            'description': u'Covers a lot of the data.',
            'script': self.test_phonology_script
        })
        params = json.dumps(params)
        response = self.app.put(url('phonology', id=phonology_id), params,
                        self.json_headers, admin)
        resp = json.loads(response.body)
        phonology_count = Session.query(model.Phonology).count()
        assert response.content_type == 'application/json'
        assert phonology_count == 1

        # Now Update the phonology as the default contributor to create a second backup.
        params = self.phonology_create_params.copy()
        params.update({
            'name': u'Phonology Renamed by Contributor',
            'description': u'Covers a lot of the data.',
            'script': self.test_phonology_script
        })
        params = json.dumps(params)
        response = self.app.put(url('phonology', id=phonology_id), params,
                        self.json_headers, contrib)
        resp = json.loads(response.body)
        phonology_count = Session.query(model.Phonology).count()
        assert phonology_count == 1

        # Now GET the phonology backups (as the viewer).
        response = self.app.get(url('phonologybackups'), headers=self.json_headers,
                                extra_environ=view)
        resp = json.loads(response.body)
        assert len(resp) == 2
        assert response.content_type == 'application/json'

        # Now update the phonology.
        params = self.phonology_create_params.copy()
        params.update({
            'name': u'Phonology Updated',
            'description': u'Covers a lot of the data.',
            'script': self.test_phonology_script
        })
        params = json.dumps(params)
        response = self.app.put(url('phonology', id=phonology_id), params,
                        self.json_headers, contrib)
        resp = json.loads(response.body)
        phonology_count = Session.query(model.Phonology).count()
        assert phonology_count == 1

        # Now GET the phonology backups.  Admin and contrib should see 4 and the
        # viewer should see 1
        response = self.app.get(url('phonologybackups'), headers=self.json_headers,
                                extra_environ=contrib)
        resp = json.loads(response.body)
        all_phonology_backups = resp
        assert len(resp) == 3

        # Test the paginator GET params.
        paginator = {'items_per_page': 1, 'page': 2}
        response = self.app.get(url('phonologybackups'), paginator,
                                headers=self.json_headers, extra_environ=admin)
        resp = json.loads(response.body)
        assert len(resp['items']) == 1
        assert resp['items'][0]['name'] == all_phonology_backups[1]['name']
        assert response.content_type == 'application/json'

        # Test the order_by GET params.
        order_by_params = {'order_by_model': 'PhonologyBackup', 'order_by_attribute': 'datetime_modified',
                     'order_by_direction': 'desc'}
        response = self.app.get(url('phonologybackups'), order_by_params,
                        headers=self.json_headers, extra_environ=admin)
        resp = json.loads(response.body)
        result_set = sorted(all_phonology_backups, key=lambda pb: pb['datetime_modified'], reverse=True)
        assert [pb['id'] for pb in resp] == [pb['id'] for pb in result_set]

        # Test the order_by *with* paginator.
        params = {'order_by_model': 'PhonologyBackup', 'order_by_attribute': 'datetime_modified',
                     'order_by_direction': 'desc', 'items_per_page': 1, 'page': 3}
        response = self.app.get(url('phonologybackups'), params,
                        headers=self.json_headers, extra_environ=admin)
        resp = json.loads(response.body)
        assert result_set[2]['name'] == resp['items'][0]['name']

        # Now test the show action:

        # Get a particular phonology backup
        response = self.app.get(url('phonologybackup', id=all_phonology_backups[0]['id']),
                                headers=self.json_headers, extra_environ=admin)
        resp = json.loads(response.body)
        assert resp['name'] == all_phonology_backups[0]['name']
        assert response.content_type == 'application/json'

        # A nonexistent pb id will return a 404 error
        response = self.app.get(url('phonologybackup', id=100987),
                    headers=self.json_headers, extra_environ=view, status=404)
        resp = json.loads(response.body)
        assert resp['error'] == u'There is no phonology backup with id 100987'
        assert response.content_type == 'application/json'

        # Attempting to call edit/new/create/delete/update on a read-only resource
        # will return a 404 response
        response = self.app.get(url('edit_phonologybackup', id=2232), status=404)
        assert json.loads(response.body)['error'] == u'This resource is read-only.'
        response = self.app.get(url('new_phonologybackup', id=2232), status=404)
        assert json.loads(response.body)['error'] == u'This resource is read-only.'
        response = self.app.post(url('phonologybackups'), status=404)
        assert json.loads(response.body)['error'] == u'This resource is read-only.'
        response = self.app.put(url('phonologybackup', id=2232), status=404)
        assert json.loads(response.body)['error'] == u'This resource is read-only.'
        response = self.app.delete(url('phonologybackup', id=2232), status=404)
        assert json.loads(response.body)['error'] == u'This resource is read-only.'
        assert response.content_type == 'application/json'
