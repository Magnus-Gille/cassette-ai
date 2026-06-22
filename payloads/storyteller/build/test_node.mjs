import fs from 'fs';
import createStoryteller from './storyteller.js';

const model = fs.readFileSync('payloads/built/stories260K_dl/stories260K/stories260K.bin');
const tok   = fs.readFileSync('payloads/built/stories260K_dl/stories260K/tok512.bin');

const M = await createStoryteller();
// load model
const mptr = M.ccall('st_alloc','number',['number'],[model.length]);
M.HEAPU8.set(model, mptr);
const tptr = M.ccall('st_alloc','number',['number'],[tok.length]);
M.HEAPU8.set(tok, tptr);
const vocab = M.ccall('st_init','number',['number','number'],[mptr, tptr]);
console.log('vocab_size =', vocab, 'seq_len =', M.ccall('st_seq_len','number',[],[]));

const prompt = 'Once upon a time';
const out = M.ccall('st_generate','string',
  ['string','number','number','number','number'],
  [prompt, 200, 0.8, 0.9, 1234]);
console.log('--- generated ---');
console.log(out);
console.log('--- tokens(approx words) ---', out.trim().split(/\s+/).length);
