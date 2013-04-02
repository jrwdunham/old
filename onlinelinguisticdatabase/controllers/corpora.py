# Copyright 2013 Joel Dunham
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

"""Contains the :class:`CorporaController` and its auxiliary functions.

.. module:: corpora
   :synopsis: Contains the corpora controller and its auxiliary functions.

"""

import logging
import datetime
import re
import os
import codecs
from uuid import uuid4
from shutil import rmtree
import simplejson as json
from string import letters, digits
from random import sample
from paste.fileapp import FileApp
from pylons import request, response, session, app_globals, config
from pylons.decorators.rest import restrict
from pylons.controllers.util import forward
from formencode.validators import Invalid
from sqlalchemy.exc import OperationalError, InvalidRequestError
from sqlalchemy.sql import asc
from sqlalchemy.orm import joinedload
from onlinelinguisticdatabase.lib.base import BaseController
from onlinelinguisticdatabase.lib.schemata import CorpusSchema, CorpusFormatSchema
import onlinelinguisticdatabase.lib.helpers as h
from onlinelinguisticdatabase.lib.SQLAQueryBuilder import SQLAQueryBuilder, OLDSearchParseError
from onlinelinguisticdatabase.model.meta import Session
from onlinelinguisticdatabase.model import Corpus, CorpusBackup, CorpusFile, Form

log = logging.getLogger(__name__)

class CorporaController(BaseController):
    """Generate responses to requests on corpus resources.

    REST Controller styled on the Atom Publishing Protocol.

    .. note::
    
       The ``h.jsonify`` decorator converts the return value of the methods to
       JSON.

    """
    queryBuilder = SQLAQueryBuilder('Corpus', config=config)

    @h.jsonify
    @h.restrict('GET')
    @h.authenticate
    def index(self):
        """Get all corpus resources.

        :URL: ``GET /corpora`` with optional query string parameters for
            ordering and pagination.
        :returns: a list of all corpus resources.

        .. note::

           See :func:`utils.addOrderBy` and :func:`utils.addPagination` for the
           query string parameters that effect ordering and pagination.

        """
        try:
            query = h.eagerloadCorpus(Session.query(Corpus))
            query = h.addOrderBy(query, dict(request.GET), self.queryBuilder)
            return h.addPagination(query, dict(request.GET))
        except Invalid, e:
            response.status_int = 400
            return {'errors': e.unpack_errors()}

    @h.jsonify
    @h.restrict('POST')
    @h.authenticate
    @h.authorize(['administrator', 'contributor'])
    def create(self):
        """Create a new corpus resource and return it.

        :URL: ``POST /corpora``
        :request body: JSON object representing the corpus to create.
        :returns: the newly created corpus.

        """
        try:
            schema = CorpusSchema()
            values = json.loads(unicode(request.body, request.charset))
            values['forms'] = getFormReferences(values.get('content', u''))
            state = h.getStateObject(values)
            data = schema.to_python(values, state)
            corpus = createNewCorpus(data)
            Session.add(corpus)
            Session.commit()
            createCorpusDir(corpus)
            return corpus
        except h.JSONDecodeError:
            response.status_int = 400
            return h.JSONDecodeErrorResponse
        except Invalid, e:
            response.status_int = 400
            return {'errors': e.unpack_errors()}

    @h.jsonify
    @h.restrict('GET')
    @h.authenticate
    @h.authorize(['administrator', 'contributor'])
    def new(self):
        """Return the data necessary to create a new corpus.

        :URL: ``GET /corpora/new``.
        :returns: a dictionary of resources.

        .. note::
        
           See :func:`h.getDataForNewAction` to understand how the query
           string parameters can affect the contents of the lists in the
           returned dictionary.

        """
        return getDataForNewEdit(dict(request.GET))

    @h.jsonify
    @h.restrict('PUT')
    @h.authenticate
    @h.authorize(['administrator', 'contributor'])
    def update(self, id):
        """Update a corpus and return it.
        
        :URL: ``PUT /corpora/id``
        :Request body: JSON object representing the corpus with updated attribute values.
        :param str id: the ``id`` value of the corpus to be updated.
        :returns: the updated corpus model.

        """
        corpus = h.eagerloadCorpus(Session.query(Corpus)).get(int(id))
        if corpus:
            try:
                schema = CorpusSchema()
                values = json.loads(unicode(request.body, request.charset))
                state = h.getStateObject(values)
                state.id = id
                values['forms'] = h.getIdsOfFormsReferenced(values.get('content', u''))
                data = schema.to_python(values, state)
                corpusDict = corpus.getDict()
                corpus = updateCorpus(corpus, data)
                # corpus will be False if there are no changes (cf. updateCorpus).
                if corpus:
                    backupCorpus(corpusDict)
                    Session.add(corpus)
                    Session.commit()
                    return corpus
                else:
                    response.status_int = 400
                    return {'error':
                        u'The update request failed because the submitted data were not new.'}
            except h.JSONDecodeError:
                response.status_int = 400
                return h.JSONDecodeErrorResponse
            except Invalid, e:
                response.status_int = 400
                return {'errors': e.unpack_errors()}
        else:
            response.status_int = 404
            return {'error': 'There is no corpus with id %s' % id}

    @h.jsonify
    @h.restrict('DELETE')
    @h.authenticate
    @h.authorize(['administrator', 'contributor'])
    def delete(self, id):
        """Delete an existing corpus and return it.

        :URL: ``DELETE /corpora/id``
        :param str id: the ``id`` value of the corpus to be deleted.
        :returns: the deleted corpus model.

        """
        corpus = h.eagerloadCorpus(Session.query(Corpus)).get(id)
        if corpus:
            corpusDict = corpus.getDict()
            backupCorpus(corpusDict)
            Session.delete(corpus)
            Session.commit()
            removeCorpusDirectory(corpus)
            return corpusDict
        else:
            response.status_int = 404
            return {'error': 'There is no corpus with id %s' % id}

    @h.jsonify
    @h.restrict('GET')
    @h.authenticate
    def show(self, id):
        """Return a corpus.
        
        :URL: ``GET /corpora/id``
        :param str id: the ``id`` value of the corpus to be returned.
        :returns: a corpus model object.

        """
        corpus = h.eagerloadCorpus(Session.query(Corpus)).get(id)
        if corpus:
            return corpus
        else:
            response.status_int = 404
            return {'error': 'There is no corpus with id %s' % id}

    @h.jsonify
    @h.restrict('GET')
    @h.authenticate
    @h.authorize(['administrator', 'contributor'])
    def edit(self, id):
        """Return a corpus and the data needed to update it.

        :URL: ``GET /corpora/edit``
        :param str id: the ``id`` value of the corpus that will be updated.
        :returns: a dictionary of the form::

                {"corpus": {...}, "data": {...}}

            where the value of the ``corpus`` key is a dictionary
            representation of the corpus and the value of the ``data`` key
            is an empty dictionary.

        """
        corpus = h.eagerloadCorpus(Session.query(Corpus)).get(id)
        if corpus:
            return {'data': getDataForNewEdit(request.GET),
                    'corpus': corpus}
        else:
            response.status_int = 404
            return {'error': 'There is no corpus with id %s' % id}

    @h.jsonify
    @h.restrict('GET')
    @h.authenticate
    def history(self, id):
        """Return the corpus with ``corpus.id==id`` and its previous versions.

        :URL: ``GET /corpora/id/history``
        :param str id: a string matching the ``id`` or ``UUID`` value of the
            corpus whose history is requested.
        :returns: A dictionary of the form::

                {"corpus": { ... }, "previousVersions": [ ... ]}

            where the value of the ``corpus`` key is the corpus whose
            history is requested and the value of the ``previousVersions`` key
            is a list of dictionaries representing previous versions of the
            corpus.

        """
        corpus, previousVersions = h.getModelAndPreviousVersions('Corpus', id)
        if corpus or previousVersions:
            return {'corpus': corpus,
                    'previousVersions': previousVersions}
        else:
            response.status_int = 404
            return {'error': 'No corpora or corpus backups match %s' % id}

    @h.jsonify
    @h.restrict('PUT')
    @h.authenticate
    @h.authorize(['administrator', 'contributor'])
    def writetofile(self, id):
        """Write the corpus to a file in the format specified in the request body.

        :URL: ``PUT /corpora/id/writetofile``
        :Request body: JSON object of the form ``{"format": "..."}.``
        :param str id: the ``id`` value of the corpus.
        :returns: the modified corpus model (or a JSON error message).

        .. note::
        
            NEEDS WORK.  Might be a good idea to compare file creation times and
            warn the user if they might be updating a file needlessly...

        """
        corpus = h.eagerloadCorpus(Session.query(Corpus), eagerloadForms=True).get(id)
        if corpus:
            try:
                schema = CorpusFormatSchema
                values = json.loads(unicode(request.body, request.charset))
                format_ = schema.to_python(values)['format']
                corpusDirPath = getCorpusDirPath(corpus)
                return writeToFile(corpus, format_)
            except Invalid, e:
                response.status_int = 400
                return {'errors': e.unpack_errors()}
            except h.JSONDecodeError:
                response.status_int = 400
                return h.JSONDecodeErrorResponse
        else:
            response.status_int = 404
            return {'error': 'There is no corpus with id %s' % id}

    @h.restrict('GET')
    @h.authenticateWithJSON
    def servefile(self, id, fileId):
        """Return the corpus as a file in the format specified in the URL query string.

        :URL: ``PUT /corpora/id/servefile/fileId``.
        :param str id: the ``id`` value of the corpus.
        :param str id: the ``id`` value of the corpus file.
        :returns: the file data

        """
        corpus = Session.query(Corpus).get(id)
        if corpus:
            try:
                corpusFile = filter(lambda cf: cf.id == int(fileId), corpus.files)[0]
                corpusFilePath = os.path.join(getCorpusDirPath(corpus),
                                              '%s.gz' % corpusFile.filename)
                if authorizedToAccessCorpusFile(session['user'], corpusFile):
                    return forward(FileApp(corpusFilePath))
                else:
                    response.status_int = 403
                    return json.dumps(h.unauthorizedMsg)
            except Exception:
                response.status_int = 400
                return json.dumps({'error': 'Unable to serve corpus file %d of corpus %d' % (
                        fileId, id)})
        else:
            response.status_int = 404
            return json.dumps({'error': 'There is no corpus with id %s' % id})


def authorizedToAccessCorpusFile(user, corpusFile):
    """Return True if user is authorized to access the corpus file."""
    if corpusFile.restricted and user.role != u'administrator' and \
    user not in h.getUnrestrictedUsers():
        return False
    return True


def getFormReferences(corpusContent):
    """Return the forms referenced in the input corpus content, in the order they were referenced."""
    if corpusContent:
        return [int(id) for id in h.formReferencePattern.findall(corpusContent)]
    return []


def writeToFile(corpus, format_):
    """Write the corpus to file in the specified format.

    Write the corpus to a binary file, create or update a corpus file model and
    associate it to the corpus model (if necessary).

    :param corpus: a corpus model.
    :param str format_: the form of the file to be written.
    :returns: the corpus modified appropriately (assuming success)
    :side effects: may write a file to disk and update/create a corpus file model.

    .. note::
    
        It may be desirable/necessary to perform the corpus file writing
        asynchronously using a dedicated corpus-file-worker.  

    """

    errorMsg = lambda msg: {'error': u'Unable to write corpus %d to file with format "%s". (%s)' % (
                corpus.id, format_, msg)}

    def updateCorpusFile(corpus, filename, modifier, datetimeModified, restricted):
        """Update the corpus file model of ``corpus`` that matches ``filename``."""
        corpusFile = [cf for cf in corpus.files if cf.filename == corpusFilename][0]
        corpusFile.restricted = restricted
        corpusFile.modifier = user
        corpusFile.datetimeModified = corpus.datetimeModified = now

    def generateNewCorpusFile(corpus, filename, format_, creator, datetimeCreated, restricted):
        """Create a corpus file model with ``filename`` and append it to ``corpus.files``."""
        corpusFile = CorpusFile()
        corpusFile.restricted = restricted
        corpus.files.append(corpusFile)
        corpusFile.filename = filename
        corpusFile.format = format_
        corpusFile.creator = corpusFile.modifier = creator
        corpusFile.datetimeCreated = corpusFile.datetimeModified = datetimeCreated
        corpus.datetimeModified = datetimeCreated

    def destroyFile(filePath):
        try:
            rmtree(filePath)
        except Exception:
            pass

    corpusFilePath = getCorpusFilePath(corpus, format_)
    update = os.path.exists(corpusFilePath) # If True, we are upating
    restricted = False

    # Create the corpus file on the filesystem
    try:
        writer = h.corpusFormats[format_]['writer']
        if corpus.formSearch:   # ``formSearch`` value negates any content.
            queryBuilder = SQLAQueryBuilder()
            forms = queryBuilder.getSQLAQuery(json.loads(corpus.formSearch.search)).\
                        options(joinedload(Form.tags)).all()
            with codecs.open(corpusFilePath, 'w', 'utf8') as f:
                for form in forms:
                    if not restricted and "restricted" in [t.name for t in form.tags]:
                        restricted = True
                    f.write(writer(form))
        else:
            formReferences = getFormReferences(corpus.content)
            forms = dict([(f.id, f) for f in corpus.forms])
            with codecs.open(corpusFilePath, 'w', 'utf8') as f:
                for id in formReferences:
                    form = forms[id]
                    if not restricted and "restricted" in [t.name for t in form.tags]:
                        restricted = True
                    f.write(writer(form))
        h.compressFile(corpusFilePath)
    except Exception, e:
        destroyFile(corpusFilePath)
        response.status_int = 400
        return errorMsg(e)

    # Update/create the corpusFile object
    try:
        now = h.now()
        user = session['user']
        corpusFilename = os.path.split(corpusFilePath)[1]
        if update:
            try:
                updateCorpusFile(corpus, filename, modifier, datetimeModified,
                                 restricted)
            except Exception:
                generateNewCorpusFile(corpus, corpusFilename, format_, user,
                                      now, restricted)
        else:
            generateNewCorpusFile(corpus, corpusFilename, format_, user, now,
                                  restricted)
    except Exception, e:
        destroyFile(corpusFilePath)
        response.status_int = 400
        return errorMsg(e)
    Session.commit()
    return corpus


################################################################################
# Backup corpus
################################################################################

def backupCorpus(corpusDict):
    """Backup a corpus.

    :param dict corpusDict: a representation of a corpus model.
    :returns: ``None``

    """
    corpusBackup = CorpusBackup()
    corpusBackup.vivify(corpusDict)
    Session.add(corpusBackup)


################################################################################
# Corpus Create & Update Functions
################################################################################

def createNewCorpus(data):
    """Create a new corpus.

    :param dict data: the data for the corpus to be created.
    :returns: an SQLAlchemy model object representing the corpus.

    .. note::
    
        I have opted not to complicate corpora by giving meaning to the
        "restricted" tag where they are concerned.  Given that a corpus' forms
        can be determined by a form search model and are therefore variable, it
        does not seem practical to toggle restricted status based on the status
        of any number of forms.  The corpus files that may be associated to a
        corpus by requesting ``PUT /corpora/id/writetofile`` may, however, be
        restricted if a restricted form is written to file.

    """
    corpus = Corpus()
    corpus.UUID = unicode(uuid4())
    corpus.name = h.normalize(data['name'])
    corpus.description = h.normalize(data['description'])
    corpus.content = h.normalize(data['content'])
    corpus.formSearch = data['formSearch']
    corpus.tags = data['tags']
    corpus.forms = data['forms']
    corpus.enterer = corpus.modifier = session['user']
    corpus.datetimeModified = corpus.datetimeEntered = h.now()
    return corpus

def updateCorpus(corpus, data):
    """Update a corpus.

    :param corpus: the corpus model to be updated.
    :param dict data: representation of the updated corpus.
    :returns: the updated corpus model or, if ``changed`` has not been set
        to ``True``, ``False``.

    """
    changed = False
    # Unicode Data
    changed = h.setAttr(corpus, 'name', h.normalize(data['name']), changed)
    changed = h.setAttr(corpus, 'description', h.normalize(data['description']), changed)
    changed = h.setAttr(corpus, 'content', h.normalize(data['content']), changed)
    changed = h.setAttr(corpus, 'formSearch', data['formSearch'], changed)

    corpus.tags = data['tags']
    corpus.forms = data['forms']

    # Many-to-Many Data: tags & forms
    # Update only if the user has made changes.
    formsToAdd = [f for f in data['forms'] if f]
    tagsToAdd = [t for t in data['tags'] if t]
    if set(formsToAdd) != set(corpus.forms):
        corpus.forms = formsToAdd
        changed = True
    if set(tagsToAdd) != set(corpus.tags):
        corpus.tags = tagsToAdd
        changed = True

    if changed:
        corpus.modifier = session['user']
        corpus.datetimeModified = h.now()
        return corpus
    return changed

def createCorpusDir(corpus):
    """Create the directory to hold the various forms of the corpus written to disk.
    
    :param corpus: a corpus model object.
    :returns: an absolute path to the directory for the corpus.

    """
    corpusDirPath = getCorpusDirPath(corpus)
    h.makeDirectorySafely(corpusDirPath)
    return corpusDirPath

def getCorpusFilePath(corpus, format_):
    """Return the path to a corpus's file of the given format.
    
    :param corpus: a corpus model object.
    :param str format_: the format for writing the corpus file.
    :returns: an absolute path to the corpus's file.

    .. note::
    
        It will be necessary to figure out other formats.

    """
    ext = h.corpusFormats[format_]['extension']
    sfx = h.corpusFormats[format_]['suffix']
    return os.path.join(getCorpusDirPath(corpus),
            'corpus_%d%s.%s' % (corpus.id, sfx, ext))

def getCorpusDirPath(corpus):
    return os.path.join(h.getOLDDirectoryPath('corpora', config=config),
                        'corpus_%d' % corpus.id)

def removeCorpusDirectory(corpus):
    """Remove the directory of the corpus model and everything in it.
    
    :param corpus: a corpus model object.
    :returns: an absolute path to the directory for the corpus.

    """
    try:
        corpusDirPath = getCorpusDirPath(corpus)
        rmtree(corpusDirPath)
        return corpusDirPath
    except Exception:
        return None


def getDataForNewEdit(GET_params):
    """Return the data needed to create a new corpus or edit one."""
    mandatoryAttributes = ['corpusFormats']
    modelNameMap = {
        'formSearches': 'FormSearch',
        'users': 'User',
        'tags': 'Tag'
    }
    getterMap = {
        'formSearches': h.getMiniDictsGetter('FormSearch'),
        'users': h.getMiniDictsGetter('User'),
        'tags': h.getMiniDictsGetter('Tag'),
        'corpusFormats': lambda: h.corpusFormats.keys()
    }
    return h.getDataForNewAction(GET_params, getterMap, modelNameMap, mandatoryAttributes)