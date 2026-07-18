from __future__ import annotations


class GuardedExitRecognition:
    """Recognize state whose constructed guard cannot outlive an exit.

    A state row is local to an exit when every guard required by that exit is
    also required by the state row.  The state therefore cannot testify on a
    continuing path and is not a competing function result.
    """

    @staticmethod
    def terminal_local_state(state_guards, exits) -> bool:
        from sugar_lift_py_tests.ir import not_

        state_guards = tuple(state_guards)
        if not state_guards:
            return False
        remainders = tuple(
            tuple(guard for guard in exit_guards if guard not in state_guards)
            for exit_guards in (
                tuple(getattr(exit_value, "guards", ())) for exit_value in exits
            )
            if all(guard in exit_guards for guard in state_guards)
        )
        if not remainders:
            return False

        def covers(partition) -> bool:
            if any(not guards for guards in partition):
                return True
            guard = partition[0][0]
            opposite = not_(guard)
            when_true = []
            when_false = []
            for guards in partition:
                if guard in guards:
                    remaining = list(guards)
                    remaining.remove(guard)
                    when_true.append(tuple(remaining))
                elif opposite in guards:
                    remaining = list(guards)
                    remaining.remove(opposite)
                    when_false.append(tuple(remaining))
            return (
                bool(when_true)
                and bool(when_false)
                and covers(tuple(when_true))
                and covers(tuple(when_false))
            )

        return covers(remainders)
