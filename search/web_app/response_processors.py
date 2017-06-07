import json
import re
import os


class SentenceViewer:
    """
    Contains methods for turning the JSON response of ES into
    viewable html.
    """

    rxWordNo = re.compile('^w[0-9]+_([0-9]+)$')

    def __init__(self, settings_dir, search_client):
        self.settings_dir = settings_dir
        f = open(os.path.join(self.settings_dir, 'corpus.json'),
                 'r', encoding='utf-8')
        self.settings = json.loads(f.read())
        f.close()
        self.name = self.settings['corpus_name']
        self.sentence_props = ['text']
        self.sc = search_client

    def build_ana_div(self, ana):
        """
        Build the contents of a div with one particular analysis.
        """
        result = ''
        if 'lex' in ana:
            result += '<span class="popup_lex">' + ana['lex'] + '</span> '
        if 'gr.pos' in ana:
            result += '<span class="popup_pos">' + ana['gr.pos'] + '</span> '
        for field in sorted(ana):
            if field not in ['lex', 'gr.pos']:
                value = ana[field]
                if type(value) == list:
                    value = ', '.join(value)
                result += '<span class="popup_field">' + field +\
                          ': <span class="popup_value">' + value + '</span></span>'
        return result

    def build_ana_popup(self, word, matchingAnalyses=None):
        """
        Build a string for a popup with the word and its analyses. 
        """
        if matchingAnalyses is None:
            matchingAnalyses = []
        popup = '<div class="popup_word">'
        if 'wf' in word:
            popup += '<span class="popup_wf">' + word['wf'] + '</span>'
        if 'ana' in word:
            for iAna in range(len(word['ana'])):
                popup += '<div class="popup_ana'
                if iAna in matchingAnalyses:
                    popup += ' popup_match'
                popup += '">'
                if len(word['ana']) > 1:
                    popup += str(iAna + 1) + '. '
                popup += self.build_ana_div(word['ana'][iAna])
                popup += '</div>'
        popup += '</div>'
        return popup

    def prepare_analyses(self, words, indexes, matchWordOffsets=None):
        """
        Generate viewable analyses for the words with given indexes.
        """
        result = ''
        for iStr in indexes:
            mWordNo = self.rxWordNo.search(iStr)
            if mWordNo is None:
                continue
            i = int(mWordNo.group(1))
            if i < 0 or i >= len(words):
                continue
            word = words[i]
            if word['wtype'] != 'word':
                continue
            matchingAnalyses = []
            if matchWordOffsets is not None and iStr in matchWordOffsets:
                matchingAnalyses = [offAna[1] for offAna in matchWordOffsets[iStr]]
            result += self.build_ana_popup(word, matchingAnalyses)
        result = result.replace('"', "&quot;").replace('<', '&lt;').replace('>', '&gt;')
        return result

    def build_span(self, sentSrc, curWords, matchWordOffsets):
        curClass = ''
        if any(wn.startswith('w') for wn in curWords):
            curClass += ' word '
        if any(wn.startswith('p') for wn in curWords):
            curClass += ' para '
        curClass = curClass.lstrip()

        if 'word' in curClass:
            dataAna = self.prepare_analyses(sentSrc['words'], curWords, matchWordOffsets).replace('"', "&quot;").replace('<', '&lt;').replace('>', '&gt;')
        else:
            dataAna = ''

        def highlightClass(nWord):
            if nWord in matchWordOffsets:
                return ' wmatch' + ''.join(' wmatch_' + str(n)
                                           for n in set(anaOff[0]
                                                        for anaOff in matchWordOffsets[nWord]))
            return ''

        spanStart = '<span class="' + curClass + \
                    ' '.join(wn + highlightClass(wn)
                             for wn in curWords) + '" data-ana="' + dataAna + '">'
        return spanStart

    def add_highlighted_offsets(self, offStarts, offEnds, text):
        """
        Find highlighted fragments in source text of the sentence
        and store their offsets in the respective lists.
        """
        indexSubtr = 0  # <em>s that appeared due to highlighting should be subtracted
        for i in range(len(text) - 4):
            if text[i] != '<':
                continue
            if text[i:i+4] == '<em>':
                try:
                    offStarts[i - indexSubtr].add('smatch')
                except KeyError:
                    offStarts[i - indexSubtr] = {'smatch'}
                indexSubtr += 4
            elif text[i:i+5] == '</em>':
                try:
                    offEnds[i - indexSubtr].add('smatch')
                except KeyError:
                    offEnds[i - indexSubtr] = {'smatch'}
                indexSubtr += 5

    def process_sentence_header(self, sentSource):
        """
        Retrieve the metadata of the document the sentence
        belongs to. Return an HTML string with this data that
        can serve as a header for the context on the output page.
        """
        result = '<span class="context_header" data-meta="">'
        docID = sentSource['doc_id']
        meta = self.sc.get_doc_by_id(docID)
        if (meta is None
                or 'hits' not in meta
                or 'hits' not in meta['hits']
                or len(meta['hits']['hits']) <= 0):
            return result + '</span>'
        meta = meta['hits']['hits'][0]
        if '_source' not in meta:
            return result + '</span>'
        meta = meta['_source']
        if 'title' in meta:
            result += '<span class="ch_title">' + meta['title'] + '</span>'
        else:
            result += '<span class="ch_title">-</span>'
        if 'author' in meta:
            result += '<span class="ch_author">' + meta['author'] + '</span>'
        if 'issue' in meta and len(meta['issue']) > 0:
            result += '<span class="ch_date">' + meta['issue'] + '</span>'
        if 'year1' in meta and 'year2' in meta:
            dateDisplayed = str(meta['year1'])
            if meta['year2'] != meta['year1']:
                dateDisplayed += '&ndash;' + str(meta['year2'])
            result += '<span class="ch_date">' + dateDisplayed + '</span>'
        dataMeta = ''
        for metaField in self.settings['viewable_meta']:
            try:
                metaValue = meta[metaField]
                if type(metaValue) != str:
                    metaValue = str(metaValue)
                dataMeta += metaField + ': ' + metaValue + '\\n'
            except KeyError:
                pass
        dataMeta = dataMeta.replace('"', '&quot;')
        if len(dataMeta) > 0:
            result = result.replace('data-meta=""', 'data-meta="' + dataMeta + '"')
        return result + '</span>'

    def get_word_offsets(self, sSource, numSent):
        """
        Find at which offsets which word start and end.
        Return two dicts, one with start offsets and the other with end offsets.
        The keys are offsets and the values are the string IDs of the words.
        """
        offStarts, offEnds = {}, {}
        for iWord in range(len(sSource['words'])):
            try:
                if sSource['words'][iWord]['wtype'] != 'word':
                    continue
                offStart, offEnd = sSource['words'][iWord]['off_start'], sSource['words'][iWord]['off_end']
            except KeyError:
                continue
            wn = 'w' + str(numSent) + '_' + str(iWord)
            try:
                offStarts[offStart].add(wn)
            except KeyError:
                offStarts[offStart] = {wn}
            try:
                offEnds[offEnd].add(wn)
            except KeyError:
                offEnds[offEnd] = {wn}
        return offStarts, offEnds

    def get_para_offsets(self, sSource):
        """
        Find at which offsets which parallel fragments start and end.
        Return two dicts, one with start offsets and the other with end offsets.
        The keys are offsets and the values are the string IDs of the fragments.
        """
        offStarts, offEnds = {}, {}
        if 'para_alignment' not in sSource or 'doc_id' not in sSource:
            return offStarts, offEnds
        docID = sSource['doc_id']
        for iPA in range(len(sSource['para_alignment'])):
            pa = sSource['para_alignment'][iPA]
            try:
                offStart, offEnd = pa['off_start'], pa['off_end']
            except KeyError:
                continue
            pID = 'p' + pa['para_id'] + str(docID)
            try:
                offStarts[offStart].add(pID)
            except KeyError:
                offStarts[offStart] = {pID}
            try:
                offEnds[offEnd].add(pID)
            except KeyError:
                offEnds[offEnd] = {pID}
        return offStarts, offEnds

    def process_sentence(self, s, numSent=1, getHeader=False, lang=''):
        """
        Process one sentence taken from response['hits']['hits'].
        If getHeader is True, retrieve the metadata from the database.
        Return dictionary {'header': document header HTML,
                           {'languages': {'<language_name>': {'text': sentence HTML}}}}.
        """
        if '_source' not in s:
            return {'languages': {lang: {'text': ''}}}
        matchWordOffsets = self.retrieve_highlighted_words(s, numSent)
        sSource = s['_source']
        if 'text' not in sSource or len(sSource['text']) <= 0:
            return {'languages': {lang: {'text': ''}}}

        header = {}
        if getHeader:
            header = self.process_sentence_header(sSource)
        if 'highlight' in s and 'text' in s['highlight']:
            highlightedText = s['highlight']['text']
            if type(highlightedText) == list:
                if len(highlightedText) > 0:
                    highlightedText = highlightedText[0]
                else:
                    highlightedText = sSource['text']
        else:
            highlightedText = sSource['text']
        if 'words' not in sSource:
            return {'languages': {lang: {'text': highlightedText}}}
        chars = list(sSource['text'])
        offParaStarts, offParaEnds = self.get_para_offsets(sSource)
        offStarts, offEnds = self.get_word_offsets(sSource, numSent)
        self.add_highlighted_offsets(offStarts, offEnds, highlightedText)

        curWords = set()
        for i in range(len(chars)):
            if chars[i] == '\n':
                if (i == 0 or i == len(chars) - 1
                        or all(chars[j] == '\n'
                               for j in range(i+1, len(chars)))):
                    chars[i] = '<span class="newline"></span>'
                else:
                    chars[i] = '<br>'
            if (i not in offStarts and i not in offEnds
                    and i not in offParaStarts and i not in offParaEnds):
                continue
            addition = ''
            if len(curWords) > 0:
                addition = '</span>'
                if i in offEnds:
                    curWords -= offEnds[i]
                if i in offParaEnds:
                    curWords -= offParaEnds[i]
            newWord = False
            if i in offStarts:
                curWords |= offStarts[i]
                newWord = True
            if i in offParaStarts:
                curWords |= offParaStarts[i]
                newWord = True
            if len(curWords) > 0 and (len(addition) > 0 or newWord):
                addition += self.build_span(sSource, curWords, matchWordOffsets)
            chars[i] = addition + chars[i]
        if len(curWords) > 0:
            chars[-1] += '</span>'
        relationsSatisfied = True
        if 'relations_satisfied' in s and not s['relations_satisfied']:
            relationsSatisfied = False
        return {'header': header, 'languages': {lang: {'text': ''.join(chars)}},
                'relations_satisfied': relationsSatisfied}

    def count_word_subcorpus_stats(self, w, docIDs):
        """
        Return statistics about the given word in the subcorpus
        specified by the list of document IDs.
        """
        query = {'bool':
                 {'must':
                  [{'term': {'w_id': w['_id']}},
                   {'terms': {'d_id': docIDs}}]
                  }
                 }
        aggFreq = {'agg_freq': {'stats': {'field': 'freq'}}}
        esQuery = {'query': query, 'aggs': aggFreq, 'size': 1}
        response = self.sc.get_word_freqs(esQuery)
        nSents, rank = '', ''   # for now
        if 'hits' not in response or 'total' not in response['hits']:
            return '?', '?', '?', '?'
        nDocs = str(response['hits']['total'])
        if 'aggregations' in response and 'agg_freq' in response['aggregations']:
            freq = str(int(response['aggregations']['agg_freq']['sum']))
        else:
            freq = '0'
        return freq, rank, nSents, nDocs

    def process_word(self, w, docIDs):
        """
        Process one word taken from response['hits']['hits'].
        """
        if '_source' not in w:
            return ''
        wSource = w['_source']
        freqAll = str(wSource['freq'])
        rankAll = str(wSource['rank'])
        nSentsAll = str(wSource['n_sents'])
        nDocsAll = str(wSource['n_docs'])
        if docIDs is None or len(docIDs) <= 0:
            freq = freqAll
            rank = rankAll
            nSents = nSentsAll
            nDocs = nDocsAll
        else:
            freq, rank, nSents, nDocs = self.count_word_subcorpus_stats(w, docIDs)
        word = '<tr><td><span class="word" data-ana="' +\
               self.build_ana_popup(wSource).replace('"', "&quot;").replace('<', '&lt;').replace('>', '&gt;') +\
               '">' + wSource['wf'] +\
               '</span></td><td>' + freq +\
               '</span></td><td>' + rank +\
               '</td><td>' + nSents +\
               '</td><td>' + nDocs +\
               '</td><td><span class="search_w" data-wf="' +\
               wSource['wf'] + '">&gt;&gt; GO!</td></tr>'
        return word

    def process_doc(self, d):
        """
        Process one document taken from response['hits']['hits'].
        """
        if '_source' not in d:
            return ''
        dSource = d['_source']
        doc = '<tr>'
        dateDisplayed = '-'
        if 'year1' in dSource:
            dateDisplayed = str(dSource['year1'])
            if 'year2' in dSource and dSource['year2'] != dSource['year1']:
                dateDisplayed += '&ndash;' + str(dSource['year2'])
        for field in self.sc.qp.docMetaFields:
            if field in dSource:
                doc += '<td>' + dSource[field] + '</td>'
            else:
                doc += '<td></td>'
        doc += '</tr>\n'
        return doc

    def retrieve_highlighted_words(self, sentence, numSent, queryWordID=''):
        """
        Explore the inner_hits part of the response to find the
        offsets of the words that matched the word-level query
        and offsets of the respective analyses, if any.
        Search for word offsets recursively, so that the procedure
        does not depend excatly on the response structure.
        Return a dictionary where keys are offsets of highlighted words
        and values are sets of the pairs (ID of the words, ID of its ana)
        that were found by the search query .
        """
        if 'inner_hits' in sentence:
            return self.retrieve_highlighted_words(sentence['inner_hits'],
                                                   numSent,
                                                   queryWordID)

        offsets = {}    # query term ID -> highlights for this query term
        if type(sentence) == list:
            for el in sentence:
                if type(el) not in [dict, list]:
                    continue
                newOffsets = self.retrieve_highlighted_words(el, numSent, queryWordID)
                for newK, newV in newOffsets.items():
                    if newK not in offsets:
                        offsets[newK] = newV
                    else:
                        offsets[newK] |= newV
            return offsets
        elif type(sentence) == dict:
            if 'field' in sentence and sentence['field'] == 'words':
                if 'offset' in sentence:
                    wordOffset = 'w' + str(numSent) + '_' + str(sentence['offset'])
                    if wordOffset not in offsets:
                        offsets[wordOffset] = set()
                    if queryWordID == '':
                        queryWordID = 'w0'
                    anaOffset = -1
                    if ('_nested' in sentence
                            and 'field' in sentence['_nested']
                            and sentence['_nested']['field'] == 'ana'):
                        anaOffset = sentence['_nested']['offset']
                    offsets[wordOffset].add((queryWordID, anaOffset))
                return offsets
            for k, v in sentence.items():
                curQueryWordID = queryWordID
                if re.search('^w[0-9]+$', k) is not None:
                    if len(queryWordID) > 0 and queryWordID != k:
                        continue
                    elif len(queryWordID) <= 0:
                        curQueryWordID = k
                if type(v) in [dict, list]:
                    newOffsets = self.retrieve_highlighted_words(v, numSent, curQueryWordID)
                    for newK, newV in newOffsets.items():
                        if newK not in offsets:
                            offsets[newK] = newV
                        else:
                            offsets[newK] |= newV
        return offsets

    def process_sent_json(self, response):
        result = {'n_occurrences': 0, 'n_sentences': 0,
                  'n_docs': 0, 'page': 1,
                  'message': 'Nothing found.'}
        if 'hits' not in response or 'total' not in response['hits']:
            return result
        result['message'] = ''
        result['n_sentences'] = response['hits']['total']
        result['contexts'] = []
        if 'aggregations' in response and 'agg_ndocs' in response['aggregations']:
            result['n_docs'] = response['aggregations']['agg_ndocs']['value']
        for iHit in range(len(response['hits']['hits'])):
            if 'lang' in response['hits']['hits'][iHit]['_source']:
                langID = response['hits']['hits'][iHit]['_source']['lang']
            else:
                langID = 0
            lang = self.settings['languages'][langID]
            curContext = self.process_sentence(response['hits']['hits'][iHit],
                                               numSent=iHit,
                                               getHeader=True,
                                               lang=lang)
            result['contexts'].append(curContext)
        return result

    def process_word_json(self, response, docIDs):
        result = {'n_occurrences': 0, 'n_sentences': 0, 'n_docs': 0, 'message': 'Nothing found.'}
        if ('hits' not in response
                or 'total' not in response['hits']
                or response['hits']['total'] <= 0):
            return result
        result['message'] = ''
        result['n_occurrences'] = response['hits']['total']
        result['n_docs'] = response['aggregations']['agg_ndocs']['value']
        result['words'] = []
        for iHit in range(len(response['hits']['hits'])):
            result['words'].append(self.process_word(response['hits']['hits'][iHit], docIDs))
        return result

    def process_docs_json(self, response):
        result = {'n_words': 0, 'n_sentences': 0, 'n_docs': 0, 'message': 'Nothing found.',
                  'metafields': self.sc.qp.docMetaFields}
        if ('hits' not in response
                or 'total' not in response['hits']
                or response['hits']['total'] <= 0):
            return result
        result['message'] = ''
        result['n_docs'] = response['hits']['total']
        result['docs'] = []
        for iHit in range(len(response['hits']['hits'])):
            result['docs'].append(self.process_doc(response['hits']['hits'][iHit]))
        return result
