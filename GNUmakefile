.PHONY: all clean

all: build/presentation.pdf

clean:
	$(RM) -r build

presentation_attachments = \
	GNUmakefile \
	commands.yaml \
	header.tex \
	meta.yaml \
	shell.nix \
	shell.py \
	what-changed \
	zlib-cat
build/presentation.pdf: build/presentation-noattach.pdf $(presentation_attachments)
	qpdf build/presentation-noattach.pdf $(foreach f,$(presentation_attachments),--add-attachment $(f) --) $@
build/presentation-noattach.pdf: build/presentation.tex
	latexmk -g -xelatex -output-directory=$(@D) -jobname=$(@F:.pdf=) build/presentation.tex < /dev/null
build/presentation.tex: meta.yaml header.tex build/parts/.done
	mkdir -p $(@D)
	pandoc --standalone -t beamer --slide-level=2 -o $@.tmp --metadata-file=meta.yaml --include-in-header=header.tex build/parts/*.md
	sed -e 's,\\textcolor\[HTML\]{00aa00},\\textcolor[HTML]{008800},' -i $@.tmp
	mv $@.tmp $@

build/parts/.done: shell.py commands.yaml
	$(RM) -r $(@D)
	mkdir -p $(@D)
	touch $@.tmp
	./shell.py -o $(@D) -i commands.yaml
	mv $@.tmp $@
