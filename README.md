# MediaLibFpGenerator
acoustId fingerprints generator and meta data retriever reuses base legacy functionality from [MediaLibManager](https://github.com/Igorigorizh/MediaLibManager) repo.
As a [MediaLibManager](https://github.com/Igorigorizh/MediaLibManager) fpgenerator service support many audio formats including single CUE images, multy tracks CUE images, hi-res flac, dsf, mp3 and others.

When necessary single CUE image is splitted into tracks via ffmpeg decoder to extract single track audio data for the next finger print processing.

On top of cue processing CD TOC data from logs is used for more precise album meta data identification and validation throughout
[acoustId](https://acoustid.org/webservice) and [MusicBrainz](https://musicbrainz.org/doc/MusicBrainz_API) API services. 

Since fingerprint processing in general decodes a high volume of audio data which is a very CPU consuming  we use here async celery tasks. 

Redis is used as a message broker and partially as a result backend.

fpgenerator Service is Dockerized and has four services inside:
1. fpgenerator - fingerprint process generation with the async celery tasks
2. fp_web - FastAPI web application to trigger, monitor and control generation process
3. Redis  - broker and temp data storage
4. Flower - celery tasks dashboard to monitor celery jobs execution

