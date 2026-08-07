#!/usr/bin/env groovy
// Parses Groovy syntax only (GroovyShell.parse). Does not validate the
// Jenkins Declarative model — use ``make lint-pipelines`` for that.
import org.codehaus.groovy.control.MultipleCompilationErrorsException

int failures = 0

if (args.length == 0) {
	System.err.println('usage: groovy scripts/lint_pipelines.groovy <file>...')
	System.exit(2)
}

args.each { String path ->
	File file = new File(path)
	if (!file.isFile()) {
		System.err.println("error: not a file: ${path}")
		failures++
		return
	}
	try {
		new GroovyShell().parse(file)
		println("OK ${path}")
	} catch (MultipleCompilationErrorsException e) {
		failures++
		e.errorCollector.errors.each { err ->
			def cause = err.cause
			Integer line = cause?.hasProperty('startLine') ? cause.startLine : null
			Integer column = cause?.hasProperty('startColumn') ? cause.startColumn : null
			String where = (line != null && column != null) ? "${path}:${line}:${column}" : path
			String message = cause?.message ?: err.toString()
			System.err.println("error: ${where}: ${message}")
		}
	} catch (Throwable t) {
		failures++
		System.err.println("error: ${path}: ${t.message ?: t}")
	}
}

System.exit(failures == 0 ? 0 : 1)
