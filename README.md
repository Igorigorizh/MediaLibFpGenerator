# MediaLibFpGenerator
acoustId fingerprints generator and meta data retriever reuses base functionality from [MediaLibManager](https://github.com/Igorigorizh/MediaLibManager) repo.
As a [MediaLibManager](https://github.com/Igorigorizh/MediaLibManager) fpgenerator service support many audio formats including single CUE images and multy tracks CUE images.

When necessary single CUE image is splited into tracks via ffmpeg decoder to extract single track audio data.

On top of cue processing TOC data from logs is used for more precise album meta data identification and validation throughout [acoustId](https://acoustid.org/webservice) and [musicbrainz](https://musicbrainz.org/doc/MusicBrainz_API) APIs. 

Since fingerprint processing in general can decode a high volume of audio data which is a very CPU consuming  we use here async celery tasks. 

Redis is used as a message broker and partialy as a result backend.