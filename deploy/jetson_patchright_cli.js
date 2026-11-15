#!/usr/bin/env node
// Node 16 compatibility polyfills
try {
  const sw = require('stream/web');
  for (const k of Object.keys(sw)) {
    if (!global[k]) global[k] = sw[k];
  }
} catch (e) {}

if (!global.TransformStream) global.TransformStream = class TransformStream {};
if (!global.ReadableStream) global.ReadableStream = class ReadableStream {};
if (!global.WritableStream) global.WritableStream = class WritableStream {};
if (!global.Request) global.Request = class Request {};
if (!global.Response) global.Response = class Response {};
if (!global.Headers) global.Headers = class Headers {};
if (!global.FormData) global.FormData = class FormData {};

/**
 * Copyright (c) Microsoft Corporation.
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 * http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */
const { libCli, libCliTestStub } = require('./lib/coreBundle');
const { program } = require('./lib/utilsBundle');
libCli.decorateProgram(program);
libCliTestStub.decorateProgram(program);
program.parse(process.argv);

