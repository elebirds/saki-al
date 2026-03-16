package common

type ConversionIssue struct {
	Code    string
	Message string
}

type ConversionReport struct {
	Warnings []ConversionIssue
	Errors   []ConversionIssue
}

func (r *ConversionReport) AddWarning(code, message string) {
	r.Warnings = append(r.Warnings, ConversionIssue{
		Code:    code,
		Message: message,
	})
}

func (r *ConversionReport) AddError(code, message string) {
	r.Errors = append(r.Errors, ConversionIssue{
		Code:    code,
		Message: message,
	})
}

func (r ConversionReport) HasBlockingErrors() bool {
	return len(r.Errors) > 0
}
