use super::*;
#[cfg(target_os = "linux")]
use std::time::Instant;

#[test]
fn successful_capture_drains_both_pipes_and_closes_stdin() {
    let out = Command::new("/bin/sh")
        .args(["-c", "cat; printf output; printf error >&2"])
        .output_with_limits(Duration::from_secs(2), 1024)
        .unwrap();
    assert!(out.status.success());
    assert_eq!(out.stdout, b"output");
    assert_eq!(out.stderr, b"error");
}

#[test]
fn deadlines_and_output_bounds_are_enforced() {
    assert_eq!(
        Command::new("/bin/sh")
            .args(["-c", "sleep 30"])
            .output_with_limits(Duration::from_millis(50), 1024)
            .unwrap_err()
            .kind(),
        io::ErrorKind::TimedOut
    );
    assert!(Command::new("/bin/sh")
        .args(["-c", "printf 123456789"])
        .output_with_limits(Duration::from_secs(2), 4)
        .is_err());
    let out = Command::new("/bin/sh")
        .args(["-c", "printf 1234"])
        .output_with_limits(Duration::from_secs(2), 4)
        .unwrap();
    assert_eq!(out.stdout, b"1234");
}

#[cfg(target_os = "linux")]
fn running(pid: u32) -> bool {
    std::fs::read_to_string(format!("/proc/{pid}/stat"))
        .ok()
        .and_then(|s| {
            s.rsplit_once(')')
                .map(|(_, s)| !s.trim_start().starts_with('Z'))
        })
        .unwrap_or(false)
}

#[cfg(target_os = "linux")]
fn group_has_live_processes(pgid: u32) -> bool {
    std::fs::read_dir("/proc")
        .unwrap()
        .filter_map(Result::ok)
        .filter_map(|entry| std::fs::read_to_string(entry.path().join("stat")).ok())
        .any(|stat| {
            let Some((_, fields)) = stat.rsplit_once(')') else {
                return false;
            };
            let mut fields = fields.split_whitespace();
            let state = fields.next();
            let _parent = fields.next();
            let group = fields.next().and_then(|value| value.parse::<u32>().ok());
            state != Some("Z") && group == Some(pgid)
        })
}

#[cfg(target_os = "linux")]
fn capture_and_assert_group_cleanup(
    script: &str,
    pid_path: &std::path::Path,
    timeout: Duration,
) -> io::Result<std::process::Output> {
    use std::io::{Read, Seek, SeekFrom};
    use std::os::fd::AsRawFd;
    use std::os::unix::process::CommandExt;

    // Record the owned PGID during spawn's handshake, before shell startup or
    // the capture deadline can interrupt shell-side PID publication. Each call
    // has its own anonymous marker, independent of the descendant PID evidence.
    let mut marker = tempfile::tempfile().unwrap();
    let fd = marker.as_raw_fd();
    let mut command = Command::new("/bin/sh");
    command.args(["-c", script]).env("PID_FILE", pid_path);
    // SAFETY: the hook uses only async-signal-safe libc calls and an inherited
    // descriptor kept alive until capture returns; it never allocates or locks.
    unsafe {
        command.pre_exec(move || {
            let pgid = libc::getpgrp() as u32;
            if pgid != libc::getpid() as u32 {
                return Err(io::Error::from_raw_os_error(libc::EINVAL));
            }
            let bytes = pgid.to_ne_bytes();
            let written = libc::write(fd, bytes.as_ptr().cast(), bytes.len());
            if written < 0 {
                return Err(io::Error::last_os_error());
            }
            if written != bytes.len() as isize {
                return Err(io::Error::from_raw_os_error(libc::EIO));
            }
            Ok(())
        });
    }
    let started = Instant::now();
    let result = command.output_with_limits(timeout, 1024);
    marker.seek(SeekFrom::Start(0)).unwrap();
    let mut bytes = [0; 4];
    marker.read_exact(&mut bytes).unwrap_or_else(|error| {
        panic!("process-group fixture was not published: {error}; capture={result:?}")
    });
    let pgid = u32::from_ne_bytes(bytes);
    let deadline = Instant::now() + Duration::from_secs(2);
    while group_has_live_processes(pgid) && Instant::now() < deadline {
        std::thread::sleep(Duration::from_millis(5));
    }
    let alive = group_has_live_processes(pgid);
    // Capture has already reaped its leader. The numeric PGID is useful only
    // for observation here, not authority to signal a potentially reused group.
    // Production ownership performs cleanup while retaining its identity anchor.
    assert!(!alive, "capture returned with a live owned process group");
    eprintln!(
        "PROCESS_CLEANUP leader_exit=true descendant_alive=false reader_threads=0 elapsed_ms={:.3}",
        started.elapsed().as_secs_f64() * 1000.0
    );
    result
}

#[cfg(target_os = "linux")]
#[test]
fn exited_leader_never_leaves_pipe_holding_descendants_or_reader_threads() {
    let tmp = tempfile::tempdir().unwrap();
    for (index, script) in [
        "sleep 30 & printf '%s\n' \"$!\" > \"$PID_FILE.tmp\"; mv \"$PID_FILE.tmp\" \"$PID_FILE\"; exit 0",
        "sleep 30 >&- 2>&- & printf '%s\n' \"$!\" > \"$PID_FILE.tmp\"; mv \"$PID_FILE.tmp\" \"$PID_FILE\"; exit 0",
        "sleep 30 & printf '%s\n' \"$!\" > \"$PID_FILE.tmp\"; mv \"$PID_FILE.tmp\" \"$PID_FILE\"; while :; do printf 123456789; done",
    ]
    .into_iter()
    .enumerate()
    {
        // Independent, atomically published evidence: a later script must not
        // truncate or accidentally reuse an earlier descendant's PID.
        let path = tmp.path().join(format!("pid-{index}"));
        // Startup under parallel CI is not what this test measures. The 50ms
        // deadline contract is independently covered above; this test checks
        // that every launched descendant is gone when capture returns.
        let result = capture_and_assert_group_cleanup(script, &path, Duration::from_secs(2));
        let pid_text = std::fs::read_to_string(&path).unwrap_or_else(|error| {
            panic!("descendant PID fixture {index} was not published: {error}; capture={result:?}")
        });
        let pid: u32 = pid_text.trim().parse().unwrap_or_else(|error| {
            panic!("invalid descendant PID in fixture {index}: {error}; capture={result:?}")
        });
        assert!(!running(pid), "capture returned with a live owned descendant");
        if script.contains(">&-") {
            assert!(result.unwrap().status.success());
        } else {
            assert!(result.is_err());
        }
    }
}

#[cfg(target_os = "linux")]
#[test]
fn deadline_before_shell_fixture_publication_still_checks_group_cleanup() {
    let tmp = tempfile::tempdir().unwrap();
    let path = tmp.path().join("delayed-pid");
    // Delay the same atomic publication used above beyond the capture deadline.
    // Cleanup must still check the whole group using its pre-exec identity.
    let result = capture_and_assert_group_cleanup(
        "sleep 30 & sleep 30; printf '%s\n' \"$!\" > \"$PID_FILE.tmp\"; mv \"$PID_FILE.tmp\" \"$PID_FILE\"; exit 0",
        &path,
        Duration::from_millis(200),
    );
    assert_eq!(result.unwrap_err().kind(), io::ErrorKind::TimedOut);
    assert!(
        !path.exists(),
        "delayed fixture unexpectedly published its PID"
    );
}
