"""Central registry of generated functions with status and version history."""
import json
from dataclasses import dataclass, field, asdict


@dataclass
class Func:
    id: int
    name: str
    description: str
    code: str
    status: str = "pending"          # pending | accepted | rejected | refined
    sample_values: list = field(default_factory=list)
    versions: list = field(default_factory=list)   # earlier (name, description, code)
    warnings: list = field(default_factory=list)   # e.g. constant output on all samples


class Registry:
    def __init__(self):
        self.funcs = []

    def add(self, name, description, code, sample_values=()):
        f = Func(len(self.funcs), name, description, code, sample_values=list(sample_values))
        self.funcs.append(f)
        return f

    def set_status(self, fid, status):
        assert status in {"pending", "accepted", "rejected", "refined"}
        self.funcs[fid].status = status

    def refine(self, fid, name, description, code, sample_values=()):
        f = self.funcs[fid]
        f.versions.append((f.name, f.description, f.code))
        f.name, f.description, f.code, f.sample_values = name, description, code, list(sample_values)
        f.status = "pending"

    def accepted(self):
        return [f for f in self.funcs if f.status == "accepted"]

    def accepted_names(self):
        return [f.name for f in self.accepted()]

    def save(self, path):
        with open(path, "w", encoding="utf-8") as fh:
            json.dump([asdict(f) for f in self.funcs], fh, indent=1)
