// pre_wad.js — prepended via --pre-js, so it is compiled INSIDE the closure
// unit and can reference FS by its (consistently renamed) direct name.
// The HTML shell passes the rawpack-decoded IWAD as Module['wadBinary'];
// string-keyed access survives closure. Path must match -DDG_IWAD_PATH.
Module['preRun'] = function() {
  FS.writeFile('/doom2.wad', Module['wadBinary']);
};
