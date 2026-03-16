package workspace

type Workspace struct {
	Root string
}

func New(root string) Workspace {
	return Workspace{Root: root}
}
