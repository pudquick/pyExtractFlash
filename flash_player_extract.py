import re, struct, os, stat, os.path, sys, subprocess, pipes, shutil

def error_quit(why_msg):
    print why_msg
    sys.exit(1)

def extract_flash_player_from_pkg(pkg_path, out_path):
    # Assuming this is a non-flat package extracted from the .app in the enterprise distribution .dmg
    # out_path should be a directory to move the plugin to (and work out of)
    pkg_path =  os.path.abspath(pkg_path)
    try:
        os.chdir(out_path)
    except:
        error_quit('! Unable to reach out_path at: %s' % os.path.abspath(out_path))
    archive    = os.path.abspath(os.path.join(pkg_path, 'Contents', 'Archive.pax.gz'))
    try:
        # This line gunzips the Archive.pax to stdout, which pipes to pax to unpack a specific file (but change its output directory)
        _ = subprocess.check_call("gunzip -c %s | pax -r -s ',./Library,./LLibrary,' './Library/Internet Plug-Ins/Flash Player.plugin.lzma'" % pipes.quote(archive), shell=True)
    except:
        error_quit('! Unable to decompress Archive.pax.gz at: %s' % archive)

    postflight = os.path.abspath(os.path.join(pkg_path, 'Contents', 'Resources', 'postflight'))
    try:
        f = open(postflight, 'rb')
        executable = f.read()
        f.close()
    except:
        error_quit('! Unable to read postflight at: %s' % postflight)
    print "* Attempting patching ..."
    r_PerformMain = r'\x5D\xC3\x55.{1,30}\xE8....\x85.\x0F\x85..\x00\x00'
    # This signature matches:
    # - End of a procedure (\x5D\xC3 = pop ebp, ret)
    # - Beginning of a procedure (\x55 = push ebp) (PerformMain itself, hopefully...)
    # - Up to 30 opcodes.
    # - A procedure call opcode with a 4 byte relative address followed by a test (\xE8....\x85.)
    # - A jump if not equal with a 4 byte relative address less than 65k (\x0F\x85..\x00\x00)
    # This should hopefully be distinct enough to always match PerformMain as it immediately calls the lzma
    # decompression routine and then checks to see if it succeeded.
    matches = [x for x in re.finditer(r_PerformMain, executable)]
    if len(matches) == 1:
        # Only proceed if there's a single match, otherwise error out
        match_obj  = matches[0]
        match_code = match_obj.group()
        # Address is little-endian signed 4 byte integer
        rel_jump_addr = struct.unpack("<i",match_code[-4:])[0]
        # The offset to the 'exit code 1' operand is relative to the start of the next instruction
        error_offset = rel_jump_addr + match_obj.end()
        # The bulk of the procedure (from beginning to error exit at end)
        perform_main = executable[match_obj.start():error_offset]
        # Find the last xor followed by a short jump (x31.xEB.)
        r_SafeExit = r'\x31.\xEB.'
        matches = [x for x in re.finditer(r_SafeExit, perform_main)]
        if len(matches) >= 1:
            # Only proceed if there's at least one match, otherwise error out
            # The one we want is the last match, right before the end
            safe_exit = matches[-1]
            # Find out how far back from the end it is
            safe_exit_offset = len(perform_main) - safe_exit.start()
            # Adjust the old jump
            new_rel_jump_addr = rel_jump_addr - safe_exit_offset
            # Repack it as an integer
            new_rel_jump_str = struct.pack("<i", new_rel_jump_addr)
            # Change out the JNE (\x0F\x85....) for a NOP + JMP (\x90\xE9....)
            new_match_code = match_code[:-6] + '\x90\xE9' + new_rel_jump_str
            # Replace the code in the executable
            new_executable = executable[:match_obj.start()] + new_match_code + executable[match_obj.end():]
            # Replace all absolute instances of "/Library/Internet" with "LLibrary/Internet" (a relative path instead of absolute)
            new_executable = new_executable.replace('/Library/Internet', 'LLibrary/Internet')
            # Write it back out
            f = open('postflight.patched', 'wb')
            f.write(new_executable)
            f.close()
            # chmod it +x
            os.chmod('postflight.patched', os.stat('postflight.patched').st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        else:
            error_quit('! postflight has changed and is unrecognizable, submit a ticket')
    else:
        error_quit('! postflight has changed and is unrecognizable, submit at ticket')
    print "* Attempting execution of patch ..."
    try:
        _ = subprocess.check_call("./postflight.patched", shell=True)
    except:
        error_quit('! Something may have gone wrong with Flash Player decompression, check in LLibrary in the output directory')
    try:
        shutil.move(os.path.join('LLibrary', 'Internet Plug-Ins', 'Flash Player.plugin'), './.')
    except:
        error_quit('! Something may have gone wrong with Flash Player decompression, plugin seems to be missing .. ?')
    # Cleanup
    shutil.rmtree('LLibrary')
    os.remove('postflight.patched')

extract_flash_player_from_pkg('extracted/Adobe Flash Player.pkg', 'extracted/out')
print "Done!"
